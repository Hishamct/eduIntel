"""
One-off script to seed portal_help_docs with onboarding/help content.
Run manually: python -m app.rag.seed_portal_help
Safe to re-run — uses upsert, so it overwrites existing entries by ID.
"""

from app.rag.client import get_portal_help_collection

PORTAL_HELP_ARTICLES = [
    {
        "id": "student_homework_upload",
        "title": "How to submit homework",
        "content": (
            "To submit homework, go to the Homework page from the sidebar. "
            "Select the pending assignment you want to submit from the list on the left. "
            "Then drag and drop your file — a PDF, DOCX, or a photo of your handwritten work — "
            "into the upload box on the right, or click it to browse your files. "
            "Once your file is selected, click Submit Homework. "
            "You can track the status of all your submissions in the Homework Submission History table at the bottom of the page, "
            "including your score and any feedback once a teacher has graded it."
        ),
    },
    {
        "id": "student_doubt_forum",
        "title": "How to ask a doubt",
        "content": (
            "If you're stuck on a concept, use the Doubt Forum from the sidebar to ask your teacher or classmates. "
            "Click New Doubt, choose the subject, write a clear title, and describe your question in detail. "
            "Once posted, teachers or other students can reply directly in the thread. "
            "You'll see all your open and resolved doubts listed, and you can reply to an existing thread "
            "if you have a follow-up question instead of creating a new one."
        ),
    },
    {
        "id": "student_study_materials",
        "title": "How to find study materials",
        "content": (
            "Study materials uploaded by your teachers — notes, question papers, and reference documents — "
            "are available on the Study Materials page. "
            "You can browse materials by subject. Each entry shows the title, subject, and a preview of its content "
            "when the material has been processed for text search."
        ),
    },
    {
        "id": "student_self_evaluation",
        "title": "How self-evaluation works",
        "content": (
            "The Self-Evaluation page gives you a personal view of your academic progress, "
            "including your homework completion rate, scores over time, and areas that may need more focus. "
            "This helps you track your own performance without waiting for a formal report."
        ),
    },
    {
        "id": "student_dashboard_overview",
        "title": "Understanding your dashboard",
        "content": (
            "Your Dashboard is the first page you see after logging in. "
            "It shows a quick summary of your pending homework count, unresolved doubts, and recent activity — "
            "including your latest homework submissions and doubt forum posts — so you always know what needs your attention."
        ),
    },
    {
        "id": "account_password_reset",
        "title": "How to reset your password",
        "content": (
            "If you forget your password, click Forgot Password on the login page. "
            "Enter the email address associated with your account, and you'll receive instructions "
            "to reset your password. Follow the link in that message to set a new password."
        ),
    },
]


def seed_portal_help_docs():
    collection = get_portal_help_collection()

    ids = [article["id"] for article in PORTAL_HELP_ARTICLES]
    documents = [f"{article['title']}\n\n{article['content']}" for article in PORTAL_HELP_ARTICLES]
    metadatas = [{"title": article["title"]} for article in PORTAL_HELP_ARTICLES]

    collection.upsert(documents=documents, ids=ids, metadatas=metadatas)

    print(f"Seeded {len(PORTAL_HELP_ARTICLES)} portal help articles into portal_help_docs.")


if __name__ == "__main__":
    seed_portal_help_docs()