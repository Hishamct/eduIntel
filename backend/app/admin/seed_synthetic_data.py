"""
One-off script to populate FeeRecord and Attendance with realistic synthetic data
for existing students, so the Admin AI Assistant has real (non-empty) tables to
query. Run manually: python -m app.admin.seed_synthetic_data
"""
import asyncio
import random
import datetime
from app.core.database import AsyncSessionLocal  # adjust import if your session factory is named differently
from sqlalchemy import select
from app.users.models import User
from app.admin.models import FeeRecord, Attendance

CLASS_SECTIONS = ["10-A", "10-B", "11-A", "11-B", "12-A"]
FEE_TYPES = ["tuition", "exam", "materials"]
MONTHS_BACK = 3


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.role == "student"))
        students = result.scalars().all()

        if not students:
            print("No students found — seed real/mock students first.")
            return

        today = datetime.date.today()
        fee_records = []
        attendance_records = []

        for student in students:
            class_section = random.choice(CLASS_SECTIONS)

            # --- Fee records: one per month for the last MONTHS_BACK months ---
            for m in range(MONTHS_BACK):
                due_date = (today.replace(day=1) - datetime.timedelta(days=30 * m)).replace(day=5)
                amount = round(random.uniform(4000, 9000), 2)

                # Realistic distribution: most paid, some pending, few overdue
                roll = random.random()
                if roll < 0.75:
                    status = "paid"
                    paid_date = due_date + datetime.timedelta(days=random.randint(-2, 10))
                elif roll < 0.90:
                    status = "pending"
                    paid_date = None
                else:
                    status = "overdue"
                    paid_date = None

                fee_records.append(FeeRecord(
                    student_id=student.id,
                    fee_type=random.choice(FEE_TYPES),
                    amount=amount,
                    due_date=due_date,
                    paid_date=paid_date,
                    payment_status=status,
                ))

            # --- Attendance: weekdays only, last MONTHS_BACK months ---
            day_cursor = today - datetime.timedelta(days=30 * MONTHS_BACK)
            while day_cursor <= today:
                if day_cursor.weekday() < 5:  # Mon-Fri only
                    roll = random.random()
                    if roll < 0.87:
                        status = "present"
                    elif roll < 0.95:
                        status = "absent"
                    else:
                        status = "late"

                    attendance_records.append(Attendance(
                        student_id=student.id,
                        class_section=class_section,
                        date=day_cursor,
                        status=status,
                    ))
                day_cursor += datetime.timedelta(days=1)

        db.add_all(fee_records)
        db.add_all(attendance_records)
        await db.commit()

        print(f"Seeded {len(fee_records)} fee records and {len(attendance_records)} attendance records for {len(students)} students.")


if __name__ == "__main__":
    asyncio.run(seed())