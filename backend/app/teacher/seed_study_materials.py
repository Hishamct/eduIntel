"""
Seeds placeholder-but-structured study materials for every (subject, topic)
combination used in the synthetic exam data, so the weak-topic recommendation
pipeline has something real to retrieve for every topic that can be flagged.
Text is templated, not genuinely pedagogical — sufficient to test that
retrieval correctly differentiates between topics via embeddings.

Run: python -m app.teacher.seed_study_materials
"""

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.rag.service import ingest_study_material
from app.teacher.models import StudyMaterial
from app.users.models import User

# Matches SUBJECT_TOPICS in app/admin/seed_ml_dataset.py exactly — keep in sync.
SUBJECT_TOPICS = {
    "MATHEMATICS": ["Algebra", "Trigonometry", "Calculus", "Geometry", "Statistics"],
    "PHYSICS": ["Mechanics", "Thermodynamics", "Optics", "Electromagnetism"],
    "CHEMISTRY": [
        "Organic Chemistry",
        "Periodic Table",
        "Chemical Bonding",
        "Acids & Bases",
    ],
    "COMPUTER SCIENCE": ["Data Structures", "Algorithms", "Databases", "Networking"],
}


def build_placeholder_text(subject: str, topic: str) -> str:
    return f"""Study Notes: {topic} ({subject})

This material covers the core concepts of {topic} as taught in the {subject} curriculum.

Key areas covered:
- Fundamental definitions and terminology related to {topic}
- Worked examples demonstrating standard problem-solving approaches for {topic}
- Common mistakes students make when studying {topic}, and how to avoid them
- Practice problems with step-by-step solutions

Students who are struggling with {topic} specifically should focus on the worked
examples section first, then attempt the practice problems independently before
checking solutions. Revisit the fundamental definitions if the practice problems
feel unfamiliar — a weak grasp of {topic}'s core terminology is the most common
root cause of difficulty in this area.

Recommended approach: review this material, attempt 3-5 practice problems, then
consult your teacher or the doubt forum for any remaining questions specific to
{topic}."""


async def seed():
    async with AsyncSessionLocal() as db:
        teacher_result = await db.execute(select(User).where(User.role == "teacher"))
        teacher = teacher_result.scalars().first()

        if not teacher:
            print(
                "No teacher account found — cannot attribute seeded materials. Create a teacher account first."
            )
            return

        created_count = 0

        for subject, topics in SUBJECT_TOPICS.items():
            for topic in topics:
                # skip if a material for this exact subject+topic combo already exists
                existing = await db.execute(
                    select(StudyMaterial).where(
                        StudyMaterial.subject == subject,
                        StudyMaterial.title == f"{topic} — Study Notes",
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                extracted_text = build_placeholder_text(subject, topic)

                material = StudyMaterial(
                    teacher_id=teacher.id,
                    subject=subject,
                    title=f"{topic} — Study Notes",
                    description=f"Auto-generated placeholder study notes for {topic}.",
                    file_path=f"synthetic/study_materials/{subject.lower().replace(' ', '_')}_{topic.lower().replace(' ', '_')}.txt",
                    original_filename=f"{topic.replace(' ', '_')}_notes.txt",
                    extracted_text=extracted_text,
                    extraction_method="synthetic_placeholder",
                )
                db.add(material)
                await db.flush()  # get material.id before commit

                try:
                    ingest_study_material(
                        material_id=material.id,
                        subject=material.subject,
                        title=material.title,
                        extracted_text=extracted_text,
                    )
                except Exception as e:
                    print(f"RAG ingestion failed for {subject}/{topic}: {e}")

                created_count += 1

        await db.commit()
        print(
            f"Seeded {created_count} study materials across {len(SUBJECT_TOPICS)} subjects."
        )


if __name__ == "__main__":
    asyncio.run(seed())
