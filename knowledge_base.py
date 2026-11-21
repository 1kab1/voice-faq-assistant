
FAQS = {
    "what is cloud computing": (
        "Cloud computing provides computing services such as "
        "servers, storage, and databases over the internet."
    ),
    "what is docker": (
        "Docker is a platform used to package applications "
        "and their dependencies into containers."
    ),
    "what is kubernetes": (
        "Kubernetes is a platform for deploying, scaling, "
        "and managing containerized applications."
    ),
    "what is python": (
        "Python is a programming language widely used for "
        "automation, web development, and machine learning."
    ),
    "what is machine learning": (
        "Machine learning enables computers to learn patterns "
        "from data and make predictions."
    ),
}


def get_answer(question):
    question = question.lower().strip()
    question = question.rstrip("?.!")

    for faq_question, answer in FAQS.items():
        if faq_question in question:
            return answer

    return (
        "Sorry, I don't know the answer to that question yet. "
        "Please try asking about cloud computing, Docker, "
        "Kubernetes, Python, or machine learning."
    )
