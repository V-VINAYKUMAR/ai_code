# Todo Application

A simple and robust Todo application built with FastAPI.

## Installation

1. Clone the repository and navigate into the project directory.
2. Install the required dependencies using `pip`:

```bash
pip install -r requirements.txt
```

## Running the Application

To run the application using `uvicorn`, use the following command:

```bash
uvicorn main:app --reload --port 8000
```

The application will be accessible at `http://localhost:8000`.

## Running Tests

To run the test suite, use `pytest`:

```bash
pytest
```