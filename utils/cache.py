"""
Caching utilities for AgriSense AI
"""
import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class SimpleCache:
    """Simple file-based cache for API responses and predictions."""
    
    def __init__(self, cache_dir: str, ttl_seconds: int = 3600):
        """
        Initialize cache.
        
        Args:
            cache_dir: Directory to store cache files
            ttl_seconds: Time-to-live for cached entries
        """
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> str:
        """Get filesystem path for cache key."""
        # Sanitize key to prevent directory traversal
        safe_key = "".join(c for c in key if c.isalnum() or c in "-_.")
        return os.path.join(self.cache_dir, f"{safe_key}.json")
    
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache if it exists and hasn't expired.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None if not found or expired
        """
        path = self._get_cache_path(key)
        
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            # Check expiration
            timestamp = data.get("timestamp", 0)
            if time.time() - timestamp > self.ttl_seconds:
                os.remove(path)
                return None
            
            return data.get("value")
        
        except Exception as e:
            log.warning(f"Cache read error for key '{key}': {e}")
            return None
    
    def set(self, key: str, value: Any) -> bool:
        """
        Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        
        Returns:
            True if successful, False otherwise
        """
        path = self._get_cache_path(key)
        
        try:
            data = {
                "key": key,
                "value": value,
                "timestamp": time.time(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            with open(path, "w") as f:
                json.dump(data, f)
            return True
        except Exception as e:
            log.warning(f"Cache write error for key '{key}': {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete cache entry."""
        path = self._get_cache_path(key)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception as e:
                log.warning(f"Cache delete error for key '{key}': {e}")
                return False
        return False
    
    def clear(self) -> int:
        """Clear all cache entries. Returns count of deleted files."""
        count = 0
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith(".json"):
                    path = os.path.join(self.cache_dir, filename)
                    try:
                        os.remove(path)
                        count += 1
                    except Exception as e:
                        log.warning(f"Error deleting cache file {filename}: {e}")
            return count
        except Exception as e:
            log.error(f"Error clearing cache: {e}")
            return 0
    
    def cleanup_expired(self) -> int:
        """Remove expired cache entries. Returns count of deleted files."""
        count = 0
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith(".json"):
                    path = os.path.join(self.cache_dir, filename)
                    try:
                        with open(path, "r") as f:
                            data = json.load(f)
                        
                        timestamp = data.get("timestamp", 0)
                        if time.time() - timestamp > self.ttl_seconds:
                            os.remove(path)
                            count += 1
                    except Exception as e:
                        log.warning(f"Error processing cache file {filename}: {e}")
            return count
        except Exception as e:
            log.error(f"Error cleaning up cache: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            files = [f for f in os.listdir(self.cache_dir) if f.endswith(".json")]
            total_size = sum(
                os.path.getsize(os.path.join(self.cache_dir, f)) 
                for f in files
            ) / (1024 * 1024)  # MB
            
            return {
                "entries": len(files),
                "size_mb": round(total_size, 2),
                "ttl_seconds": self.ttl_seconds
            }
        except Exception as e:
            log.error(f"Error getting cache stats: {e}")
            return {}


# One re-entrant lock per history file, shared by every PredictionHistory
# instance pointing at that path. Gunicorn serves requests on several threads,
# and add/delete/update are read-modify-write cycles on a JSON file - without a
# lock two simultaneous requests could overwrite each other or corrupt the file.
_HISTORY_LOCKS: Dict[str, threading.RLock] = {}
_HISTORY_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.RLock:
    key = os.path.abspath(path)
    with _HISTORY_LOCKS_GUARD:
        if key not in _HISTORY_LOCKS:
            _HISTORY_LOCKS[key] = threading.RLock()
        return _HISTORY_LOCKS[key]


class PredictionHistory:
    """Manage local prediction history (a small JSON file, max 100 entries).

    The file - and its parent folder - is created lazily on the first write, so
    merely reading history (or a bot hitting the API) never creates anything on
    disk. Writes are atomic (temp file + rename), so a crash mid-write cannot
    leave a half-written, unreadable history file.
    """

    def __init__(self, history_file: str):
        """
        Initialize prediction history manager.

        Args:
            history_file: Path to history JSON file
        """
        self.history_file = history_file
        self._lock = _lock_for(history_file)

    # -- low-level helpers -------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        """Read the history document; a missing file is simply 'no history'."""
        if not os.path.exists(self.history_file):
            return {"predictions": []}
        with open(self.history_file, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("predictions"), list):
            return {"predictions": []}
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        """Atomically write the history document."""
        directory = os.path.dirname(os.path.abspath(self.history_file))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.history_file)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # -- public API ----------------------------------------------------------
    def add(self, prediction: Dict[str, Any]) -> bool:
        """Add prediction to history."""
        try:
            with self._lock:
                data = self._read()

                # Add timestamp if not present
                if "timestamp" not in prediction:
                    prediction["timestamp"] = datetime.now(timezone.utc).isoformat()

                # Generate ID if not present
                if "id" not in prediction:
                    import hashlib
                    content = json.dumps(prediction, sort_keys=True).encode()
                    prediction["id"] = hashlib.md5(content).hexdigest()[:12]

                data["predictions"].append(prediction)

                # Keep only last 100 predictions
                if len(data["predictions"]) > 100:
                    data["predictions"] = data["predictions"][-100:]

                self._write(data)
            return True
        except Exception as e:
            log.warning(f"Error adding to history: {e}")
            return False

    def get_all(self) -> list:
        """Get all predictions from history."""
        try:
            with self._lock:
                return self._read().get("predictions", [])
        except Exception as e:
            log.warning(f"Error reading history: {e}")
            return []

    def get_recent(self, limit: int = 10) -> list:
        """Get recent predictions."""
        all_predictions = self.get_all()
        return all_predictions[-limit:]

    def delete(self, prediction_id: str) -> bool:
        """Delete prediction by ID."""
        try:
            with self._lock:
                data = self._read()
                original_count = len(data["predictions"])
                data["predictions"] = [
                    p for p in data["predictions"]
                    if p.get("id") != prediction_id
                ]
                if len(data["predictions"]) < original_count:
                    self._write(data)
                    return True
                return False
        except Exception as e:
            log.warning(f"Error deleting from history: {e}")
            return False

    def clear(self) -> bool:
        """Clear all history."""
        try:
            with self._lock:
                self._write({"predictions": []})
            return True
        except Exception as e:
            log.warning(f"Error clearing history: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get history statistics."""
        predictions = self.get_all()
        if not predictions:
            return {"total": 0, "recent_7_days": 0}
        
        # Count predictions from last 7 days
        seven_days_ago = time.time() - (7 * 24 * 3600)
        recent_count = 0
        
        for pred in predictions:
            try:
                timestamp_str = pred.get("timestamp", "")
                if timestamp_str:
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    if dt.timestamp() > seven_days_ago:
                        recent_count += 1
            except Exception:
                pass
        
        return {
            "total": len(predictions),
            "recent_7_days": recent_count
        }

    def update(self, prediction_id: str, fields: Dict[str, Any]) -> bool:
        """
        Merge additional fields into an existing history entry by id
        (e.g. cost/market-price/revenue data that arrives asynchronously
        after the base prediction was already saved). Never overwrites
        the whole record - only sets the given keys. Returns False
        (without raising) if the id isn't found or the write fails, so
        this is safe to call as a best-effort operation.
        """
        try:
            with self._lock:
                data = self._read()
                found = False
                for pred in data["predictions"]:
                    if pred.get("id") == prediction_id:
                        pred.update(fields)
                        found = True
                        break
                if not found:
                    return False
                self._write(data)
            return True
        except Exception as e:
            log.warning(f"Error updating history entry '{prediction_id}': {e}")
            return False

    def get_farm_summary(self) -> Dict[str, Any]:
        """
        Compute honest, from-the-data-only farm summary statistics.
        Every average/trend is computed only over records that actually
        have that field - it never fabricates a figure for missing data,
        and returns an explicit 'insufficient_data' flag rather than a
        zero or null that could be misread as a real value.
        """
        predictions = self.get_all()
        if not predictions:
            return {"total_predictions": 0, "insufficient_data": True}

        crops = [p.get("recommended_crop") for p in predictions if p.get("recommended_crop")]
        yields = [p.get("estimated_yield") for p in predictions if isinstance(p.get("estimated_yield"), (int, float))]
        costs = [p.get("estimated_cost") for p in predictions if isinstance(p.get("estimated_cost"), (int, float))]
        areas = [p.get("farm_area_ha") for p in predictions if isinstance(p.get("farm_area_ha"), (int, float))]
        margins = [p.get("estimated_gross_margin") for p in predictions
                   if isinstance(p.get("estimated_gross_margin"), (int, float))]

        latest = predictions[-1]

        summary = {
            "total_predictions": len(predictions),
            "unique_crops_evaluated": len(set(crops)) if crops else 0,
            "latest_recommended_crop": latest.get("recommended_crop"),
            "latest_farm_area_ha": latest.get("farm_area_ha"),
            "latest_prediction_date": latest.get("timestamp"),
            "insufficient_data": False,
        }

        summary["average_predicted_yield_t_per_ha"] = round(sum(yields) / len(yields), 2) if yields else None
        summary["average_predicted_yield_sample_size"] = len(yields)

        summary["average_estimated_cost_inr"] = round(sum(costs) / len(costs), 2) if costs else None
        summary["average_estimated_cost_sample_size"] = len(costs)

        summary["average_gross_margin_inr"] = round(sum(margins) / len(margins), 2) if margins else None
        summary["average_gross_margin_sample_size"] = len(margins)

        summary["latest_farm_area_ha"] = areas[-1] if areas else None

        # Simple trend: compare the average of the most recent half of
        # yield records against the earlier half - only when there are
        # enough records to make that comparison meaningful.
        summary["yield_trend"] = None
        if len(yields) >= 4:
            mid = len(yields) // 2
            earlier_avg = sum(yields[:mid]) / mid
            recent_avg = sum(yields[mid:]) / (len(yields) - mid)
            diff = recent_avg - earlier_avg
            if abs(diff) < 0.05:
                summary["yield_trend"] = "stable"
            elif diff > 0:
                summary["yield_trend"] = "up"
            else:
                summary["yield_trend"] = "down"

        return summary
