"""
Generates a realistic synthetic dataset: attendance, homework submissions,
and per-topic exam results for synthetic students, spanning ~10 months.

Built specifically to give the Week 4 ML models genuine learnable signal:
- Archetypes correlate overall behavior with outcomes, WITH per-student noise
  (so no single feature trivially separates at-risk vs not).
- Each student additionally gets 0-2 personal "weak topics" — topics where
  they underperform their own baseline by a consistent margin, independent
  of their overall archetype. Without this, topic has no real effect on
  score, and "weak-topic" prediction collapses into just "weak-student"
  prediction at a noisier level.

Run: python -m app.admin.seed_ml_dataset
"""
import asyncio
import random
import datetime
from app.core.database import AsyncSessionLocal  # confirm this is the real name
from app.auth.security import hash_password
from app.users.models import User, StudentProfile
from app.student.models import HomeworkSubmission
from app.teacher.models import ExamResult
from app.admin.models import Attendance

N_STUDENTS = 500
MONTHS_BACK = 10
CLASS_SECTIONS = ["8-A", "8-B", "9-A", "9-B", "10-A", "10-B", "11-A", "11-B", "12-A"]
SUBJECT_TOPICS = {
    "MATHEMATICS": ["Algebra", "Trigonometry", "Calculus", "Geometry", "Statistics"],
    "PHYSICS": ["Mechanics", "Thermodynamics", "Optics", "Electromagnetism"],
    "CHEMISTRY": ["Organic Chemistry", "Periodic Table", "Chemical Bonding", "Acids & Bases"],
    "COMPUTER SCIENCE": ["Data Structures", "Algorithms", "Databases", "Networking"],
}
ALL_TOPICS_FLAT = [(subj, t) for subj, topics in SUBJECT_TOPICS.items() for t in topics]

# --- Behavioral archetypes: (name, weight, attendance_base, homework_rate_base, exam_base, trend_per_month) ---
ARCHETYPES = [
    ("strong",         0.20,   0.95,       0.92,      85,        +0.3),
    ("average",        0.35,   0.85,       0.75,      68,         0.0),
    ("improving",      0.15,   0.80,       0.65,      55,        +1.8),
    ("declining",      0.15,   0.88,       0.80,      75,        -1.6),
    ("at_risk",        0.15,   0.65,       0.45,      42,        -0.5),
]


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def pick_archetype():
    r = random.random()
    cumulative = 0
    for name, weight, att, hw, exam, trend in ARCHETYPES:
        cumulative += weight
        if r <= cumulative:
            # Add per-student individual variance so archetypes overlap —
            # otherwise the archetype base values alone become a trivial predictor.
            att_noise = random.gauss(0, 0.08)
            hw_noise = random.gauss(0, 0.10)
            exam_noise = random.gauss(0, 10)
            trend_noise = random.gauss(0, 0.6)

            return {
                "name": name,
                "attendance": clamp(att + att_noise, 0.35, 0.99),
                "hw_rate": clamp(hw + hw_noise, 0.1, 0.98),
                "exam_base": clamp(exam + exam_noise, 10, 98),
                "trend": trend + trend_noise,
            }
    return {"name": "average", "attendance": 0.85, "hw_rate": 0.75, "exam_base": 68, "trend": 0.0}


async def seed():
    async with AsyncSessionLocal() as db:
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=30 * MONTHS_BACK)

        print(f"Generating {N_STUDENTS} synthetic students with {MONTHS_BACK} months of history...")

        students_data = []
        for i in range(N_STUDENTS):
            archetype = pick_archetype()
            class_section = random.choice(CLASS_SECTIONS)
            email = f"synth_student_{i}@eduintel.demo"

            user = User(
                email=email,
                hashed_password=hash_password("demo_password_123"),
                name=f"Synthetic Student {i}",
                role="student",
            )
            db.add(user)
            await db.flush()  # assigns user.id

            profile = StudentProfile(
                user_id=user.id,
                grade=class_section.split("-")[0],
                section=class_section.split("-")[1],
                roll_number=str(i + 1),
            )
            db.add(profile)

            # Each student gets 0-2 personal weak topics, independent of archetype.
            n_weak_topics = random.choice([0, 1, 1, 2])
            weak_topics = set(random.sample(ALL_TOPICS_FLAT, n_weak_topics)) if n_weak_topics else set()

            students_data.append({
                "user": user,
                "class_section": class_section,
                "archetype": archetype,
                "weak_topics": weak_topics,
            })

        await db.commit()
        print(f"Created {len(students_data)} student accounts.")

        attendance_records = []
        homework_records = []
        exam_records = []

        for s in students_data:
            student = s["user"]
            class_section = s["class_section"]
            arch = s["archetype"]
            weak_topics = s["weak_topics"]

            # --- Attendance: weekdays only, with a slow trend over the period ---
            day_cursor = start_date
            while day_cursor <= today:
                if day_cursor.weekday() < 5:
                    months_elapsed = (day_cursor - start_date).days / 30
                    trend_adjustment = (arch["trend"] / 100) * months_elapsed
                    attend_prob = clamp(arch["attendance"] + trend_adjustment, 0.3, 0.99)

                    roll = random.random()
                    if roll < attend_prob:
                        status = "present"
                    elif roll < attend_prob + 0.05:
                        status = "late"
                    else:
                        status = "absent"

                    attendance_records.append(Attendance(
                        student_id=student.id,
                        class_section=class_section,
                        date=day_cursor,
                        status=status,
                    ))
                day_cursor += datetime.timedelta(days=1)

            # --- Homework: weekly per subject, correlated with hw_rate ---
            subjects = list(SUBJECT_TOPICS.keys())
            week_cursor = start_date
            while week_cursor <= today:
                for subject in subjects:
                    months_elapsed = (week_cursor - start_date).days / 30
                    trend_adjustment = (arch["trend"] / 100) * months_elapsed
                    submit_prob = clamp(arch["hw_rate"] + trend_adjustment, 0.1, 0.98)

                    if random.random() < submit_prob:
                        homework_records.append(HomeworkSubmission(
                            student_id=student.id,
                            subject=subject,
                            title=f"{subject.title()} Weekly Practice",
                            description="Auto-generated synthetic submission",
                            file_path="synthetic/placeholder.pdf",
                            original_filename="placeholder.pdf",
                            status="submitted",
                        ))
                week_cursor += datetime.timedelta(days=7)

            # --- Exams: monthly per subject/topic ---
            # Score = archetype baseline + trend + noise, MINUS a consistent
            # penalty if this (subject, topic) is one of this student's
            # personal weak topics. This is what makes topic-level prediction
            # a genuinely different signal from overall at-risk prediction.
            month_cursor = start_date
            while month_cursor <= today:
                months_elapsed = (month_cursor - start_date).days / 30
                trend_adjustment = arch["trend"] * months_elapsed

                for subject, topics in SUBJECT_TOPICS.items():
                    topic = random.choice(topics)
                    base_score = arch["exam_base"] + trend_adjustment + random.gauss(0, 8)

                    if (subject, topic) in weak_topics:
                        base_score -= random.gauss(18, 5)

                    base_score = clamp(base_score, 5, 100)

                    exam_records.append(ExamResult(
                        student_id=student.id,
                        class_section=class_section,
                        subject=subject,
                        topic=topic,
                        exam_date=month_cursor,
                        score=round(base_score, 2),
                        max_score=100,
                    ))
                month_cursor += datetime.timedelta(days=30)

        print(f"Inserting {len(attendance_records)} attendance, {len(homework_records)} homework, {len(exam_records)} exam records...")

        BATCH_SIZE = 1000
        for i in range(0, len(attendance_records), BATCH_SIZE):
            db.add_all(attendance_records[i:i + BATCH_SIZE])
            await db.commit()

        for i in range(0, len(homework_records), BATCH_SIZE):
            db.add_all(homework_records[i:i + BATCH_SIZE])
            await db.commit()

        for i in range(0, len(exam_records), BATCH_SIZE):
            db.add_all(exam_records[i:i + BATCH_SIZE])
            await db.commit()

        print("Done. Synthetic dataset ready for ML training.")


if __name__ == "__main__":
    asyncio.run(seed())