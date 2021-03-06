"""Contains the User class."""

from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

from mypy_extensions import NoReturn
from pyramid.security import (
    ALL_PERMISSIONS,
    Allow,
    Authenticated,
    Deny,
    DENY_ALL,
    Everyone,
)
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Text,
    TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import deferred
from sqlalchemy.sql.expression import text
from sqlalchemy_utils import Ltree

from tildes.enums import TopicSortOption
from tildes.lib.database import ArrayOfLtree, CIText
from tildes.lib.hash import hash_string, is_match_for_hash
from tildes.models import DatabaseModel
from tildes.schemas.user import EMAIL_ADDRESS_NOTE_MAX_LENGTH, UserSchema


class User(DatabaseModel):
    """Model for a user's account on the site.

    Trigger behavior:
      Incoming:
        - num_unread_notifications will be incremented and decremented by
          insertions, deletions, and updates to is_unread in
          comment_notifications.
        - num_unread_messages will be incremented and decremented by
          insertions, deletions, and updates to unread_user_ids in
          message_conversations.
    """

    schema_class = UserSchema

    __tablename__ = 'users'

    user_id: int = Column(Integer, primary_key=True)
    username: str = Column(CIText, nullable=False, unique=True)
    password_hash: str = deferred(Column(Text, nullable=False))
    email_address_hash: Optional[str] = deferred(Column(Text))
    email_address_note: Optional[str] = deferred(
        Column(
            Text,
            CheckConstraint(
                'LENGTH(email_address_note) <= '
                f'{EMAIL_ADDRESS_NOTE_MAX_LENGTH}',
                name='email_address_note_length',
            ),
        )
    )
    created_time: datetime = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        index=True,
        server_default=text('NOW()'),
    )
    num_unread_messages: int = Column(
        Integer, nullable=False, server_default='0')
    num_unread_notifications: int = Column(
        Integer, nullable=False, server_default='0')
    inviter_id: int = Column(Integer, ForeignKey('users.user_id'))
    invite_codes_remaining: int = Column(
        Integer, nullable=False, server_default='0')
    track_comment_visits: bool = Column(
        Boolean, nullable=False, server_default='false')
    auto_mark_notifications_read: bool = Column(
        Boolean, nullable=False, server_default='false')
    open_new_tab_external: bool = Column(
        Boolean, nullable=False, server_default='false')
    open_new_tab_internal: bool = Column(
        Boolean, nullable=False, server_default='false')
    open_new_tab_text: bool = Column(
        Boolean, nullable=False, server_default='false')
    is_banned: bool = Column(Boolean, nullable=False, server_default='false')
    is_admin: bool = Column(Boolean, nullable=False, server_default='false')
    home_default_order: Optional[TopicSortOption] = Column(
        ENUM(TopicSortOption))
    home_default_period: Optional[str] = Column(Text)
    _filtered_topic_tags: List[Ltree] = Column(
        'filtered_topic_tags',
        ArrayOfLtree,
        nullable=False,
        server_default='{}',
    )

    @hybrid_property
    def filtered_topic_tags(self) -> List[str]:
        """Return the user's list of filtered topic tags."""
        return [
            str(tag).replace('_', ' ')
            for tag in self._filtered_topic_tags
        ]

    @filtered_topic_tags.setter  # type: ignore
    def filtered_topic_tags(self, new_tags: List[str]) -> None:
        self._filtered_topic_tags = new_tags

    def __repr__(self) -> str:
        """Display the user's username and ID as its repr format."""
        return f'<User {self.username} ({self.user_id})>'

    def __str__(self) -> str:
        """Use the username for the string representation."""
        return self.username

    def __init__(self, username: str, password: str) -> None:
        """Create a new user account."""
        self.username = username
        self.password = password

    def __acl__(self) -> Sequence[Tuple[str, Any, str]]:
        """Pyramid security ACL."""
        acl = [
            (Allow, Everyone, 'view'),
        ]

        # anyone can message a user except themself
        acl.append((Deny, self.user_id, 'message'))
        acl.append((Allow, Authenticated, 'message'))

        # grant the user all other permissions on themself
        acl.append((Allow, self.user_id, ALL_PERMISSIONS))

        acl.append(DENY_ALL)

        return acl

    @property
    def password(self) -> NoReturn:
        """Return an error since reading the password isn't possible."""
        raise AttributeError('Password is write-only')

    @password.setter
    def password(self, value: str) -> None:
        # need to do manual validation since some password checks depend on
        # checking the username at the same time (for similarity)
        self.schema.validate({'username': self.username, 'password': value})

        self.password_hash = hash_string(value)

    def is_correct_password(self, password: str) -> bool:
        """Check if the password is correct for this user."""
        return is_match_for_hash(password, self.password_hash)

    def change_password(self, old_password: str, new_password: str) -> None:
        """Change the user's password from the old one to a new one."""
        if not self.is_correct_password(old_password):
            raise ValueError('Old password was not correct')

        if new_password == old_password:
            raise ValueError('New password is the same as old password')

        # disable mypy on this line because it doesn't handle setters correctly
        self.password = new_password  # type: ignore

    @property
    def email_address(self) -> NoReturn:
        """Return an error since reading the email address isn't possible."""
        raise AttributeError('Email address is write-only')

    @email_address.setter
    def email_address(self, value: Optional[str]) -> None:
        """Set the user's email address (will be stored hashed)."""
        if not value:
            self.email_address_hash = None
            return

        # convert the address to lowercase to avoid potential casing issues
        value = value.lower()
        self.email_address_hash = hash_string(value)

    @property
    def num_unread_total(self) -> int:
        """Return total number of unread items (notifications + messages)."""
        return self.num_unread_messages + self.num_unread_notifications
