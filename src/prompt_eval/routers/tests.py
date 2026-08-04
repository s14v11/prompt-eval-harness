"""CRUD endpoints for test suites and their test cases."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from prompt_eval.database import get_db
from prompt_eval.models import TestCase, TestSuite
from prompt_eval.schemas import TestCaseCreate, TestCaseRead, TestSuiteCreate, TestSuiteRead

router = APIRouter(prefix="/test-suites", tags=["test-suites"])


def _get_suite_or_404(db: Session, suite_id: str) -> TestSuite:
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Test suite {suite_id!r} not found.")
    return suite


@router.get("", response_model=list[TestSuiteRead])
def list_test_suites(db: Session = Depends(get_db)) -> list[TestSuite]:
    """List all test suites, including their test cases."""
    return list(db.scalars(select(TestSuite).order_by(TestSuite.created_at.desc())))


@router.post("", response_model=TestSuiteRead, status_code=status.HTTP_201_CREATED)
def create_test_suite(payload: TestSuiteCreate, db: Session = Depends(get_db)) -> TestSuite:
    """Create a new, empty test suite."""
    existing = db.scalar(select(TestSuite).where(TestSuite.name == payload.name))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Test suite named {payload.name!r} already exists.")
    suite = TestSuite(name=payload.name, description=payload.description)
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return suite


@router.get("/{suite_id}", response_model=TestSuiteRead)
def get_test_suite(suite_id: str, db: Session = Depends(get_db)) -> TestSuite:
    """Fetch a test suite and its test cases."""
    return _get_suite_or_404(db, suite_id)


@router.delete("/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_suite(suite_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a test suite and all of its test cases."""
    suite = _get_suite_or_404(db, suite_id)
    db.delete(suite)
    db.commit()


@router.post(
    "/{suite_id}/test-cases", response_model=TestCaseRead, status_code=status.HTTP_201_CREATED
)
def create_test_case(suite_id: str, payload: TestCaseCreate, db: Session = Depends(get_db)) -> TestCase:
    """Add a new test case to a suite."""
    suite = _get_suite_or_404(db, suite_id)
    test_case = TestCase(suite_id=suite.id, **payload.model_dump())
    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    return test_case


@router.get("/{suite_id}/test-cases", response_model=list[TestCaseRead])
def list_test_cases(suite_id: str, db: Session = Depends(get_db)) -> list[TestCase]:
    """List all test cases within a suite."""
    suite = _get_suite_or_404(db, suite_id)
    return suite.test_cases


@router.delete("/{suite_id}/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(suite_id: str, case_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a single test case from a suite."""
    _get_suite_or_404(db, suite_id)
    test_case = db.get(TestCase, case_id)
    if test_case is None or test_case.suite_id != suite_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Test case {case_id!r} not found in suite.")
    db.delete(test_case)
    db.commit()
