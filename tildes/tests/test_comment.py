from datetime import timedelta

from freezegun import freeze_time
from pyramid.security import (
    Authenticated,
    Everyone,
    principals_allowed_by_permission,
)
from pytest import fixture

from tildes.enums import CommentSortOption
from tildes.lib.datetime import utc_now
from tildes.models.comment import (
    Comment,
    CommentTree,
    EDIT_GRACE_PERIOD,
)
from tildes.models.topic import Topic
from tildes.schemas.comment import CommentSchema
from tildes.schemas.fields import Markdown


@fixture
def topic(db, session_group, session_user):
    """Create a topic in the db, delete it as teardown (including comments)."""
    new_topic = Topic.create_text_topic(
        session_group, session_user, 'Some title', 'some text')
    db.add(new_topic)
    db.commit()

    yield new_topic

    db.query(Comment).filter_by(topic_id=new_topic.topic_id).delete()
    db.delete(new_topic)
    db.commit()


@fixture
def comment(db, session_user, topic):
    """Create a comment in the database, delete it as teardown."""
    new_comment = Comment(topic, session_user, 'A comment')
    db.add(new_comment)
    db.commit()

    yield new_comment

    db.delete(new_comment)
    db.commit()


def test_comment_creation_validates_schema(mocker, session_user, topic):
    """Ensure that comment creation goes through schema validation."""
    mocker.spy(CommentSchema, 'load')

    Comment(topic, session_user, 'A test comment')
    call_args = CommentSchema.load.call_args[0]
    assert {'markdown': 'A test comment'} in call_args


def test_comment_creation_uses_markdown_field(mocker, session_user, topic):
    """Ensure the Markdown field class is validating new comments."""
    mocker.spy(Markdown, '_validate')

    Comment(topic, session_user, 'A test comment')
    assert Markdown._validate.called


def test_comment_edit_uses_markdown_field(mocker, comment):
    """Ensure editing a comment is validated by the Markdown field class."""
    mocker.spy(Markdown, '_validate')

    comment.markdown = 'Some new text after edit'
    assert Markdown._validate.called


def test_comments_affect_topic_num_comments(session_user, topic, db):
    """Ensure adding/deleting comments affects the topic's comment count."""
    assert topic.num_comments == 0

    # Insert some comments, ensure each one increments the count
    comments = []
    for num in range(0, 5):
        new_comment = Comment(topic, session_user, 'comment')
        comments.append(new_comment)
        db.add(new_comment)
        db.commit()
        db.refresh(topic)
        assert topic.num_comments == len(comments)

    # Delete all the comments, ensure each one decrements the count
    for num, comment in enumerate(comments, start=1):
        comment.is_deleted = True
        db.commit()
        db.refresh(topic)
        assert topic.num_comments == len(comments) - num


def test_delete_sets_deleted_time(db, comment):
    """Ensure a deleted comment gets its deleted_time set."""
    assert not comment.is_deleted
    assert not comment.deleted_time

    comment.is_deleted = True
    db.commit()
    db.refresh(comment)

    assert comment.deleted_time


def test_edit_markdown_updates_html(comment):
    """Ensure editing a comment works and the markdown and HTML update."""
    comment.markdown = 'Updated comment'
    assert 'Updated' in comment.markdown
    assert 'Updated' in comment.rendered_html


def test_comment_viewing_permission(comment):
    """Ensure that anyone can view a comment by default."""
    assert Everyone in principals_allowed_by_permission(comment, 'view')


def test_comment_editing_permission(comment):
    """Ensure that only the comment's author can edit it."""
    principals = principals_allowed_by_permission(comment, 'edit')
    assert principals == {comment.user_id}


def test_comment_deleting_permission(comment):
    """Ensure that only the comment's author can delete it."""
    principals = principals_allowed_by_permission(comment, 'delete')
    assert principals == {comment.user_id}


def test_comment_replying_permission(comment):
    """Ensure that any authenticated user can reply to a comment."""
    assert Authenticated in principals_allowed_by_permission(comment, 'reply')


def test_deleted_comment_permissions_removed(comment):
    """Ensure that deleted comments lose all of the permissions."""
    comment.is_deleted = True
    for permission in ('view', 'edit', 'delete', 'reply'):
        assert not principals_allowed_by_permission(comment, permission)


def test_edit_grace_period(comment):
    """Ensure last_edited_time isn't set if the edit is inside grace period."""
    one_sec = timedelta(seconds=1)
    edit_time = comment.created_time + EDIT_GRACE_PERIOD - one_sec

    with freeze_time(edit_time):
        comment.markdown = 'some new markdown'

    assert not comment.last_edited_time


def test_edit_after_grace_period(comment):
    """Ensure last_edited_time is set after the grace period."""
    one_sec = timedelta(seconds=1)
    edit_time = comment.created_time + EDIT_GRACE_PERIOD + one_sec

    with freeze_time(edit_time):
        comment.markdown = 'some new markdown'
        assert comment.last_edited_time == utc_now()


def test_multiple_edits_update_time(comment):
    """Ensure multiple edits all update last_edited_time."""
    one_sec = timedelta(seconds=1)
    initial_time = comment.created_time + EDIT_GRACE_PERIOD + one_sec

    for minutes in range(0, 4):
        edit_time = initial_time + timedelta(minutes=minutes)
        with freeze_time(edit_time):
            comment.markdown = f'edit #{minutes}'
            assert comment.last_edited_time == utc_now()


def test_comment_tree(db, topic, session_user):
    """Ensure that building and pruning a comment tree works."""
    all_comments = []

    sort = CommentSortOption.POSTED

    # add two root comments
    root = Comment(topic, session_user, 'root')
    root2 = Comment(topic, session_user, 'root2')
    all_comments.extend([root, root2])
    db.add_all(all_comments)
    db.commit()

    # check that both show up in the tree as top-level comments
    tree = CommentTree(all_comments, sort)
    assert list(tree) == [root, root2]

    # delete the second root comment and check that the tree now excludes it
    root2.is_deleted = True
    db.commit()
    tree = list(CommentTree(all_comments, sort))
    assert tree == [root]

    # add two replies to the remaining root comment
    child = Comment(topic, session_user, '1', parent_comment=root)
    child2 = Comment(topic, session_user, '2', parent_comment=root)
    all_comments.extend([child, child2])
    db.add_all(all_comments)
    db.commit()

    # check that the tree is built as expected so far (one root, two replies)
    tree = list(CommentTree(all_comments, sort))
    assert tree == [root]
    assert root.replies == [child, child2]
    assert child.replies == []
    assert child2.replies == []

    # add two more replies to the second depth-1 comment
    subchild = Comment(topic, session_user, '2a', parent_comment=child2)
    subchild2 = Comment(topic, session_user, '2b', parent_comment=child2)
    all_comments.extend([subchild, subchild2])
    db.add_all(all_comments)
    db.commit()

    # check the tree again
    tree = list(CommentTree(all_comments, sort))
    assert tree == [root]
    assert root.replies == [child, child2]
    assert child.replies == []
    assert child2.replies == [subchild, subchild2]

    # delete child2 (which has replies) and ensure it stays in the tree
    child2.is_deleted = True
    db.commit()
    tree = list(CommentTree(all_comments, sort))
    assert root.replies == [child, child2]

    # delete child2's children and ensure that whole branch is pruned
    subchild.is_deleted = True
    subchild2.is_deleted = True
    db.commit()
    tree = list(CommentTree(all_comments, sort))
    assert root.replies == [child]

    # delete root and remaining child and ensure tree is empty
    child.is_deleted = True
    root.is_deleted = True
    db.commit()
    tree = list(CommentTree(all_comments, sort))
    assert not tree
