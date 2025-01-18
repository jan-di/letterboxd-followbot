import enum
from typing import List
from typing import Optional
from datetime import datetime

from sqlalchemy import ForeignKey, DateTime
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    username: Mapped[Optional[str]]
    language_code: Mapped[Optional[str]]

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, first_name={self.first_name!r}, last_name={self.last_name!r})"


class Chat(Base):
    __tablename__ = "chat"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    type: Mapped[str]

    def __repr__(self) -> str:
        return f"Chat(id={self.id!r}, title={self.title!r}, type={self.type!r})"


class FollowMemberType(enum.Enum):
    MEMBER = "member"
    FOLLOWING = "following"


class FollowMember(Base):
    __tablename__ = "follow_member"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chat.id"))
    member_id: Mapped[int]
    type: Mapped[FollowMemberType]
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"FollowMember(id={self.id!r}, chat_id={self.chat_id!r}, member_id={self.member_id!r}, type={self.type!r})"
