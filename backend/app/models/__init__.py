# Import all models here so Alembic autogenerate can discover them.
from app.models.case import Case, CaseStatus  # noqa: F401
from app.models.case_membership import CaseMemberRole, CaseMembership  # noqa: F401
from app.models.client import Client  # noqa: F401
from app.models.user import User, UserRole  # noqa: F401
