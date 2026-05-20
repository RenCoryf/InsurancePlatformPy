from fastapi import Depends, HTTPException, status

from app.api.deps.subject_auth import SubjectRow, get_current_subject


async def get_current_support(subject: SubjectRow = Depends(get_current_subject)) -> SubjectRow:
    if subject.subject.type != "support" or subject.support is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support role required")
    return subject
