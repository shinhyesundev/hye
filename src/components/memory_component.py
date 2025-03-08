import pymongo
import faiss
import numpy
import yake
import hashlib
from datetime import datetime, timedelta, timezone
from sentence_transformers import SentenceTransformer
from transformers import pipeline
from collections import Counter
from cryptography.fernet import Fernet

class MemoryComponent:
    def __init__(self, mongoose_uri="mongodb://localhost:27017/", mongoose_name="hye_memory", collection_name="hye_memory_collection", encryption_key=None):
        self.client = pymongo.MongoClient(mongoose_uri)
        self.db = self.client[mongoose_name]
        self.collection = self.db[collection_name]
        self.collection.create_index("timestamp")
        self.encryption_key = encryption_key if encryption_key else Fernet.generate_key()
        self.cipher = Fernet(self.encryption_key)
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.index = faiss.IndexIDMap(faiss.IndexFlatL2(384))
        self.next_id = 0
        self.sentiment_analyzer = pipeline("sentiment-analysis")
        self.keyword_extractor = yake.KeywordExtractor()
        self.collection.create_index([("usage_count", pymongo.ASCENDING), ("last_accessed", pymongo.ASCENDING)])

    def _encrypt_data(self, data):
        if isinstance(data, str):
            return self.cipher.encrypt(data.encode()).decode()
        return data

    def _decrypt_data(self, encrypted_data):
        if isinstance(encrypted_data, str):
            return self.cipher.decrypt(encrypted_data.encode()).decode()
        return encrypted_data

    def _remove_from_faiss_and_id_mapping(self, memory_id):
        mapping = self.db['id_mapping'].find_one({'memory_id': memory_id})
        if mapping:
            faiss_id = mapping['faiss_id']
            self.index.remove_ids(numpy.array([faiss_id], dtype=numpy.int64))
            self.db['id_mapping'].delete_one({'_id': mapping['_id']})

    def store_memory(self, content, speaker_id, tags=None, media=None, context=None):
        if media is None:
            media = []
        hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
        encrypted_speaker_id = self._encrypt_data(hashed_speaker)
        encrypted_content = self._encrypt_data(content)
        if tags is None:
            keywords = self.keyword_extractor.extract_keywords(content)
            tags = [kw[0] for kw in keywords[:3]]
        sentiment = self.sentiment_analyzer(content)[0]
        memory = {
            "content": encrypted_content,
            "content_plain": content,
            "speaker_id": encrypted_speaker_id,
            "timestamp": datetime.now(timezone.utc),
            "tags": tags,
            "media": media,
            "sentiment": sentiment,
            "context": self._encrypt_data(context) if context else None,
            "usage_count": 0,
            "last_accessed": datetime.now(timezone.utc)
        }
        memory_id = self.collection.insert_one(memory).inserted_id
        faiss_id = self.next_id
        embedding = self.model.encode([content])[0]
        self.index.add_with_ids(numpy.array([embedding], dtype=numpy.float32), numpy.array([faiss_id], dtype=numpy.int64))
        self.db['id_mapping'].insert_one({'faiss_id': faiss_id, 'memory_id': memory_id})
        self.next_id += 1

    def retrieve_memories(self, query, speaker_id=None):
        filter_query = {"content_plain": {"$regex": query, "$options": "i"}}
        if speaker_id:
            hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
            filter_query["speaker_id"] = self._encrypt_data(hashed_speaker)
        memories = list(self.collection.find(filter_query))
        return self.decrypt_memories(memories)

    def retrieve_semantic_memories(self, query, k=5, speaker_id=None):
        query_embedding = self.model.encode([query])[0]
        distances, indices = self.index.search(numpy.array([query_embedding], dtype=numpy.float32), k)
        faiss_ids = [fid for fid in indices[0] if fid != -1]
        ordered_memory_ids = []
        for faiss_id in faiss_ids:
            mapping = self.db['id_mapping'].find_one({'faiss_id': faiss_id})
            if mapping:
                ordered_memory_ids.append(mapping['memory_id'])
        filter_query = {'_id': {'$in': ordered_memory_ids}}
        if speaker_id:
            hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
            filter_query["speaker_id"] = self._encrypt_data(hashed_speaker)
        memories = list(self.collection.find(filter_query))
        memory_dict = {mem['_id']: mem for mem in memories}
        ordered_memories = [memory_dict[mid] for mid in ordered_memory_ids if mid in memory_dict]
        self._update_usage(ordered_memory_ids)
        return self.decrypt_memories(ordered_memories)

    def retrieve_by_context(self, context, k=3):
        return self.retrieve_semantic_memories(context, k)

    def retrieve_by_tags(self, tags, speaker_id=None):
        filter_query = {'tags': {'$in': tags}}
        if speaker_id:
            hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
            filter_query["speaker_id"] = self._encrypt_data(hashed_speaker)
        memories = list(self.collection.find(filter_query))
        self._update_usage([mem['_id'] for mem in memories])
        return self.decrypt_memories(memories)

    def get_viewer_interest(self, speaker_id):
        hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
        encrypted_speaker_id = self._encrypt_data(hashed_speaker)
        memories = self.collection.find({'speaker_id': encrypted_speaker_id})
        all_tags = [tag for memory in memories for tag in memory['tags']]
        common_tags = Counter(all_tags).most_common(5)
        return [tag for tag, count in common_tags]

    def _update_usage(self, memory_ids):
        self.collection.update_many(
            {'_id': {'$in': memory_ids}},
            {'$inc': {'usage_count': 1}, '$set': {'last_accessed': datetime.now(timezone.utc)}}
        )

    def decrypt_memories(self, memories):
        decrypted_memories = []
        for mem in memories:
            decrypted_mem = mem.copy()
            decrypted_mem['content'] = self._decrypt_data(mem['content'])
            decrypted_mem['speaker_id'] = "hashed"
            if mem.get('context'):
                decrypted_mem['context'] = self._decrypt_data(mem['context'])
            decrypted_memories.append(decrypted_mem)
        return decrypted_memories

    def forget_unused_memories(self, threshold_days=90, min_usage=2):
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        to_forget = list(self.collection.find({
            'last_accessed': {'$lt': cutoff},
            'usage_count': {'$lt': min_usage}
        }))
        for memory in to_forget:
            self._remove_from_faiss_and_id_mapping(memory['_id'])
            self.db["archived_memories"].insert_one(memory)
            self.collection.delete_one({'_id': memory['_id']})

    def delete_viewer_memories(self, speaker_id):
        hashed_speaker = hashlib.sha256(speaker_id.encode()).hexdigest()
        encrypted_speaker_id = self._encrypt_data(hashed_speaker)
        memories = list(self.collection.find({'speaker_id': encrypted_speaker_id}))
        for memory in memories:
            self._remove_from_faiss_and_id_mapping(memory['_id'])
        self.collection.delete_many({'speaker_id': encrypted_speaker_id})
        print(f"Memories deleted for speaker_id: {speaker_id}")
