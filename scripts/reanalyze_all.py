"""Re-analyze all corpus documents: delete old post_examples, trigger fresh analysis."""
import asyncio
import sys

import asyncpg


DB_URL = "postgresql://tce:tce@localhost:5432/tce"

# Corpus document IDs to re-analyze (all FB profiles + tom-even)
CORPUS_DOCS = [
    "d650ae15-a59b-4ab5-afb1-d09ed32f15ef",  # FB_profiles_3.docx - 0 posts
    "d198b5bd-ec2f-400f-9615-44f88f9ac655",  # FB profiles.docx - 5 posts
    "0a4e6914-84bc-46c9-8721-60fce2cabe6d",  # FB profiles (Yuval).docx - 10 posts
    "3b18102f-8119-4473-bbd4-a7b0c5dfad64",  # FB_profiles_1.docx - 11 posts
    "29791923-16c1-4107-b99c-7d6ab4791ecd",  # FB profiles (1).docx - 15 posts
    "a74c598f-644b-4e0d-ad53-a8f1c4bb7c20",  # FB_profiles_2.docx - 15 posts
    "3cdc60d2-827f-4569-93bb-5223f5d86848",  # FB_profiles_2_new.docx - 48 posts
    "33656a3c-591f-4502-9cdd-b6cc292ca3c5",  # tom-even.docx - 8 posts
]


async def main():
    conn = await asyncpg.connect(DB_URL)

    # Step 1: Delete old post_examples for all corpus docs
    for doc_id in CORPUS_DOCS:
        row = await conn.fetchrow(
            "SELECT file_name FROM source_documents WHERE id = $1::uuid", doc_id
        )
        name = row["file_name"] if row else doc_id
        deleted = await conn.fetchval(
            "DELETE FROM post_examples WHERE document_id = $1::uuid RETURNING count(*)",
            doc_id,
        )
        # fetchval with DELETE RETURNING count(*) won't work easily, use execute
        result = await conn.execute(
            "DELETE FROM post_examples WHERE document_id = $1::uuid", doc_id
        )
        count = int(result.split(" ")[-1]) if result else 0
        print(f"Cleared {count} old posts from {name}")

    await conn.close()
    print("\nAll old post_examples cleared. Now trigger re-analysis via API.")
    print("Use: curl -X POST http://localhost:8000/api/v1/pipeline/run \\")
    print('  -H "Content-Type: application/json" \\')
    print('  -d \'{"workflow": "corpus_ingestion", "context": {"document_id": "<ID>", "document_text": "<TEXT>"}}\'')


if __name__ == "__main__":
    asyncio.run(main())
