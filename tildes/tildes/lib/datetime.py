"""Functions/classes related to dates and times."""

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from ago import human


class SimpleHoursPeriod:
    """A simple class that represents a time period of hours or days."""

    _SHORT_FORM_REGEX = re.compile(r'\d+[hd]', re.IGNORECASE)

    def __init__(self, hours: int) -> None:
        """Initialize a SimpleHoursPeriod from a number of hours."""
        if hours <= 0:
            raise ValueError('Period must be at least 1 hour.')

        self.hours = hours
        self.timedelta = timedelta(hours=hours)

    @classmethod
    def from_short_form(cls, short_form: str) -> 'SimpleHoursPeriod':
        """Initialize a period from a "short form" string (e.g. "2h", "4d")."""
        if not cls._SHORT_FORM_REGEX.match(short_form):
            raise ValueError('Invalid time period')

        unit = short_form[-1].lower()
        count = int(short_form[:-1])

        if unit == 'h':
            hours = count
        elif unit == 'd':
            hours = count * 24

        return cls(hours=hours)

    def __str__(self) -> str:
        """Return a representation of the period as a string.

        Will be of the form "4 hours", "2 days", "1 day, 6 hours", etc. except
        for the special case of exactly "1 day", which is replaced with "24
        hours".
        """
        string = human(self.timedelta, past_tense='{}')
        if string == '1 day':
            string = '24 hours'

        return string

    def __eq__(self, other: Any) -> bool:
        """Equality comparison method."""
        if isinstance(other, SimpleHoursPeriod):
            return self.hours == other.hours

        return NotImplemented

    def as_short_form(self) -> str:
        """Return a representation of the period as a "short form" string.

        Uses "hours" representation unless the period is an exact multiple of
        24 hours (except for 24 hours itself).
        """
        if self.hours % 24 == 0 and self.hours != 24:
            return '{}d'.format(self.hours // 24)

        return f'{self.hours}h'


def utc_now() -> datetime:
    """Return timezone-aware current datetime in UTC timezone."""
    return datetime.now(timezone.utc)


def descriptive_timedelta(target: datetime, abbreviate: bool = False) -> str:
    """Return a descriptive string for how long ago a datetime was.

    The returned string will be of a format like "4 hours ago" or
    "3 hours, 21 minutes ago". The second "precision level" is only added if
    it will be at least minutes, and only one "level" below the first unit.
    That is, you'd never see anything like "4 hours, 5 seconds ago" or
    "2 years, 3 hours ago".

    If `abbreviate` is true, the units will be shortened to return a string
    like "12h 28m ago" instead of "12 hours, 28 minutes ago".

    A time of less than a second returns "a moment ago".
    """
    seconds_ago = (utc_now() - target).total_seconds()
    if seconds_ago < 1:
        return 'a moment ago'

    # determine whether one or two precision levels is appropriate
    if seconds_ago < 3600:
        # if it's less than an hour, we always want only one precision level
        precision = 1
    else:
        # try a precision=2 version, and check the units it ends up with
        result = human(target, precision=2)

        units = ('year', 'day', 'hour', 'minute', 'second')
        unit_indices = [i for (i, unit) in enumerate(units) if unit in result]

        # if there was only one unit in it, or they're adjacent, this is fine
        if len(unit_indices) < 2 or unit_indices[1] - unit_indices[0] == 1:
            precision = 2
        else:
            # otherwise, drop back down to precision=1
            precision = 1

    result = human(target, precision, abbreviate=abbreviate)

    # remove commas if abbreviating ("3d 2h ago", not "3d, 2h ago")
    if abbreviate:
        result = result.replace(',', '')

    return result
