from pytest import raises
from sqlalchemy.exc import IntegrityError

from tildes.models.group import Group
from tildes.schemas.fields import Ltree, SimpleString
from tildes.schemas.group import (
    GroupSchema,
    is_valid_group_path,
)


def test_empty_path_invalid():
    """Ensure empty group path is invalid."""
    assert not is_valid_group_path('')


def test_typical_path_valid():
    """Ensure a "normal-looking" group path is valid."""
    assert is_valid_group_path('games.video.nintendo_3ds')


def test_start_with_underscore():
    """Ensure you can't start a path with an underscore."""
    assert not is_valid_group_path('_x.y.z')


def test_middle_element_start_with_underscore():
    """Ensure a middle path element can't start with an underscore."""
    assert not is_valid_group_path('x._y.z')


def test_end_with_underscore():
    """Ensure you can't end a path with an underscore."""
    assert not is_valid_group_path('x.y.z_')


def test_middle_element_end_with_underscore():
    """Ensure a middle path element can't end with an underscore."""
    assert not is_valid_group_path('x.y_.z')


def test_uppercase_letters_invalid():
    """Ensure a group path can't contain uppercase chars."""
    assert is_valid_group_path('comp.lang.c')
    assert not is_valid_group_path('comp.lang.C')


def test_paths_with_invalid_characters():
    """Ensure that paths can't include some characters (not comprehensive)."""
    invalid_chars = ' ~!@#$%^&*()+={}[]|\\:;"<>,?/'

    for char in invalid_chars:
        path = f'abc{char}xyz'
        assert not is_valid_group_path(path)


def test_paths_with_unicode_characters():
    """Ensure that paths can't use unicode chars (not comprehensive)."""
    for path in ('games.pokémon', 'ポケモン', 'bites.møøse'):
        assert not is_valid_group_path(path)


def test_creation_validates_schema(mocker):
    """Ensure that group creation goes through expected validation."""
    mocker.spy(GroupSchema, 'load')
    mocker.spy(Ltree, '_validate')
    mocker.spy(SimpleString, '_validate')

    Group('testing', 'with a short description')

    assert GroupSchema.load.called
    assert Ltree._validate.call_args[0][1] == 'testing'
    assert SimpleString._validate.call_args[0][1] == 'with a short description'


def test_duplicate_group(db):
    """Ensure groups with duplicate paths can't be created."""
    original = Group('twins')
    db.add(original)
    duplicate = Group('twins')
    db.add(duplicate)

    with raises(IntegrityError):
        db.commit()
