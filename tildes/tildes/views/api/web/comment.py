"""Web API endpoints related to comments."""

from pyramid.request import Request
from pyramid.response import Response
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import FlushError
from webargs.pyramidparser import use_kwargs
from zope.sqlalchemy import mark_changed

from tildes.enums import CommentNotificationType, CommentTagOption
from tildes.lib.datetime import utc_now
from tildes.models.comment import (
    Comment,
    CommentNotification,
    CommentTag,
    CommentVote,
)
from tildes.models.topic import TopicVisit
from tildes.schemas.comment import CommentSchema, CommentTagSchema
from tildes.views import IC_NOOP
from tildes.views.decorators import ic_view_config


@ic_view_config(
    route_name='topic_comments',
    request_method='POST',
    renderer='single_comment.jinja2',
    permission='comment',
)
@use_kwargs(CommentSchema(only=('markdown',)))
def post_toplevel_comment(request: Request, markdown: str) -> dict:
    """Post a new top-level comment on a topic with Intercooler."""
    topic = request.context

    new_comment = Comment(
        topic=topic,
        author=request.user,
        markdown=markdown,
    )
    request.db_session.add(new_comment)

    if topic.user != request.user and not topic.is_deleted:
        notification = CommentNotification(
            topic.user,
            new_comment,
            CommentNotificationType.TOPIC_REPLY,
        )
        request.db_session.add(notification)

    # commit and then re-query the new comment to get complete data
    request.tm.commit()

    new_comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=new_comment.comment_id)
        .one()
    )

    return {'comment': new_comment, 'topic': topic}


@ic_view_config(
    route_name='comment_replies',
    request_method='POST',
    renderer='single_comment.jinja2',
    permission='reply',
)
@use_kwargs(CommentSchema(only=('markdown',)))
def post_comment_reply(request: Request, markdown: str) -> dict:
    """Post a reply to a comment with Intercooler."""
    parent_comment = request.context
    new_comment = Comment(
        topic=parent_comment.topic,
        author=request.user,
        markdown=markdown,
        parent_comment=parent_comment,
    )
    request.db_session.add(new_comment)

    if parent_comment.user != request.user:
        notification = CommentNotification(
            parent_comment.user,
            new_comment,
            CommentNotificationType.COMMENT_REPLY,
        )
        request.db_session.add(notification)

    # commit and then re-query the new comment to get complete data
    request.tm.commit()

    new_comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=new_comment.comment_id)
        .one()
    )

    return {'comment': new_comment}


@ic_view_config(
    route_name='comment',
    request_method='GET',
    renderer='comment_contents.jinja2',
    permission='view',
)
def get_comment_contents(request: Request) -> dict:
    """Get a comment's body with Intercooler."""
    return {'comment': request.context}


@ic_view_config(
    route_name='comment',
    request_method='GET',
    request_param='ic-trigger-name=edit',
    renderer='comment_edit.jinja2',
    permission='edit',
)
def get_comment_edit(request: Request) -> dict:
    """Get the edit form for a comment with Intercooler."""
    return {'comment': request.context}


@ic_view_config(
    route_name='comment',
    request_method='PATCH',
    renderer='comment_contents.jinja2',
    permission='edit',
)
@use_kwargs(CommentSchema(only=('markdown',)))
def patch_comment(request: Request, markdown: str) -> dict:
    """Update a comment with Intercooler."""
    comment = request.context

    comment.markdown = markdown

    return {'comment': comment}


@ic_view_config(
    route_name='comment',
    request_method='DELETE',
    renderer='comment_contents.jinja2',
    permission='delete',
)
def delete_comment(request: Request) -> dict:
    """Delete a comment with Intercooler."""
    comment = request.context
    comment.is_deleted = True

    return {'comment': comment}


@ic_view_config(
    route_name='comment_vote',
    request_method='PUT',
    permission='vote',
    renderer='comment_contents.jinja2',
)
def vote_comment(request: Request) -> dict:
    """Vote on a comment with Intercooler."""
    comment = request.context

    savepoint = request.tm.savepoint()

    new_vote = CommentVote(request.user, comment)
    request.db_session.add(new_vote)

    try:
        # manually flush before attempting to commit, to avoid having all
        # objects detached from the session in case of an error
        request.db_session.flush()
        request.tm.commit()
    except IntegrityError:
        # the user has already voted on this comment
        savepoint.rollback()

    # re-query the comment to get complete data
    comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=comment.comment_id)
        .one()
    )

    return {'comment': comment}


@ic_view_config(
    route_name='comment_vote',
    request_method='DELETE',
    permission='vote',
    renderer='comment_contents.jinja2',
)
def unvote_comment(request: Request) -> dict:
    """Remove the user's vote from a comment with Intercooler."""
    comment = request.context

    request.query(CommentVote).filter(
        CommentVote.comment == comment,
        CommentVote.user == request.user,
    ).delete(synchronize_session=False)

    # manually commit the transaction so triggers will execute
    request.tm.commit()

    # re-query the comment to get complete data
    comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=comment.comment_id)
        .one()
    )

    return {'comment': comment}


@ic_view_config(
    route_name='comment_tag',
    request_method='PUT',
    permission='tag',
    renderer='comment_contents.jinja2',
)
@use_kwargs(CommentTagSchema(only=('name',)), locations=('matchdict',))
def tag_comment(request: Request, name: CommentTagOption) -> Response:
    """Add a tag to a comment."""
    comment = request.context

    savepoint = request.tm.savepoint()

    tag = CommentTag(comment, request.user, name)
    request.db_session.add(tag)

    try:
        # manually flush before attempting to commit, to avoid having all
        # objects detached from the session in case of an error
        request.db_session.flush()
        request.tm.commit()
    except FlushError:
        savepoint.rollback()

    # re-query the comment to get complete data
    comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=comment.comment_id)
        .one()
    )

    return {'comment': comment}


@ic_view_config(
    route_name='comment_tag',
    request_method='DELETE',
    permission='tag',
    renderer='comment_contents.jinja2',
)
@use_kwargs(CommentTagSchema(only=('name',)), locations=('matchdict',))
def untag_comment(request: Request, name: CommentTagOption) -> Response:
    """Remove a tag (that the user previously added) from a comment."""
    comment = request.context

    request.query(CommentTag).filter(
        CommentTag.comment_id == comment.comment_id,
        CommentTag.user_id == request.user.user_id,
        CommentTag.tag == name,
    ).delete(synchronize_session=False)

    # commit and then re-query the comment to get complete data
    request.tm.commit()

    comment = (
        request.query(Comment)
        .join_all_relationships()
        .filter_by(comment_id=comment.comment_id)
        .one()
    )

    return {'comment': comment}


@ic_view_config(
    route_name='comment_mark_read',
    request_method='PUT',
    permission='mark_read',
)
def mark_read_comment(request: Request) -> Response:
    """Mark a comment read (clear all notifications)."""
    comment = request.context

    request.query(CommentNotification).filter(
        CommentNotification.user == request.user,
        CommentNotification.comment == comment,
    ).update(
        {CommentNotification.is_unread: False}, synchronize_session=False)

    # If the user has the "track comment visits" feature enabled, we want to
    # increment the number of comments they've seen in the thread that the
    # comment came from, so that they don't *both* get a notification as well
    # as have the thread highlight with "(1 new)". This should only happen if
    # their last visit was before the comment was posted, however.
    # Below, this is implemented as a INSERT ... ON CONFLICT DO UPDATE so that
    # it will insert a new topic visit with 1 comment if they didn't previously
    # have one at all.
    if request.user.track_comment_visits:
        statement = (
            insert(TopicVisit.__table__)
            .values(
                user_id=request.user.user_id,
                topic_id=comment.topic_id,
                visit_time=utc_now(),
                num_comments=1,
            )
            .on_conflict_do_update(
                constraint=TopicVisit.__table__.primary_key,
                set_={'num_comments': TopicVisit.num_comments + 1},
                where=TopicVisit.visit_time < comment.created_time,
            )
        )

        request.db_session.execute(statement)
        mark_changed(request.db_session)

    return IC_NOOP
