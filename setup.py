from setuptools import setup, find_packages

setup(
    name="integraldb",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
        "pdfplumber",
        "google-generativeai",
        "supabase",
        "python-dotenv",
        "pydantic",
        "streamlit",
        "apscheduler"
    ],
    entry_points={
        'console_scripts': [
            'integraldb-backend=integraldb.backend.scheduler:main',
            'integraldb-frontend=integraldb.frontend.app:main'
        ],
    },
    author="Akioin11",
    description="IntegralDB - Document Processing and RAG System",
    python_requires=">=3.8",
)