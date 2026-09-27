import logging
import os
from pymilvus import MilvusClient

logger = logging.getLogger(__name__)

class MilvusClientWrapper:
    def __init__(self, host: str, port: int):
        # We ignore host/port and use Milvus Lite (local file)
        self.uri = "/data/evidence/milvus_faces.db"
        self.collection_name = "faces"
        self.dim = 512
        self.client = None
        self._connect()

    def _connect(self):
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(self.uri), exist_ok=True)
            
            self.client = MilvusClient(uri=self.uri)
            logger.info("Successfully connected to Milvus Lite at %s", self.uri)
            self._ensure_collection()
        except Exception as e:
            logger.error("Failed to connect to Milvus: %s", e)

    def _ensure_collection(self):
        if self.client.has_collection(self.collection_name):
            logger.info("Loaded existing Milvus collection: %s", self.collection_name)
        else:
            self.client.create_collection(
                collection_name=self.collection_name,
                dimension=self.dim,
                metric_type="COSINE",
                auto_id=True,
                id_type="int"
            )
            # Create an index (Milvus Lite handles indexing automatically for basic collections)
            logger.info("Created new Milvus collection: %s", self.collection_name)

    def upsert_face(self, uuid: str, embedding: list[float], status: str):
        if not self.client:
            return

        try:
            data = [
                {"uuid": uuid, "status": status, "vector": embedding}
            ]
            res = self.client.insert(
                collection_name=self.collection_name,
                data=data
            )
            logger.info("Upserted face for uuid=%s with status=%s", uuid, status)
            return res
        except Exception as e:
            logger.error("Error upserting face to Milvus: %s", e)

    def search_face(self, embedding: list[float], status_filter: str, threshold: float):
        if not self.client:
            return None

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                data=[embedding],
                filter=f"status == '{status_filter}'",
                limit=1,
                output_fields=["uuid"]
            )

            if results and len(results[0]) > 0:
                best_match = results[0][0]
                similarity = best_match['distance']
                if similarity >= threshold:
                    logger.info("Found matching %s face with similarity %.3f", status_filter, similarity)
                    return {"uuid": best_match['entity']['uuid'], "similarity": similarity}
            
            return None
        except Exception as e:
            logger.error("Error searching face in Milvus: %s", e)
            return None

    def delete_face_by_uuid(self, uuid: str):
        if not self.client:
            return
            
        try:
            res = self.client.delete(
                collection_name=self.collection_name,
                filter=f"uuid == '{uuid}'"
            )
            logger.info("Deleted face records for uuid=%s", uuid)
            return res
        except Exception as e:
            logger.error("Error deleting face from Milvus: %s", e)

