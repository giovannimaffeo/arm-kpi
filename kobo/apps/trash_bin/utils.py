from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_delete
from django.utils.timezone import now
from django_celery_beat.models import (
    ClockedSchedule,
    PeriodicTask,
    PeriodicTasks,
)
from rest_framework import status

from hub.models import ExtraUserDetail
from kobo.apps.audit_log.models import AuditLog, AuditMethod
from kpi.models import Asset
from .exceptions import (
    TrashIntegrityError,
    TrashNotImplementedError,
    TrashTaskInProgressError,
)
from .models import TrashStatus
from .models.account import AccountTrash
from .models.project import ProjectTrash


def delete_project(request_author: 'auth.User', asset: 'kpi.Asset'):
    if asset.has_deployment:
        _delete_submissions(request_author, asset)

    with transaction.atomic():
        asset_id = asset.pk
        asset.delete()
        AuditLog.objects.create(
            app_label=asset._meta.app_label,
            model_name=asset._meta.model_name,
            object_id=asset_id,
            user=request_author,
            metadata={
                'asset_uid': asset.uid,
                'asset_name': asset.name,
            }
        )


@transaction.atomic
def move_to_trash(
    request_author: 'auth.User',
    objects_list: list[dict],
    grace_period: int,
    trash_type: str,
    delete_all: bool = False,
):
    """
    Create trash objects and their related scheduled celery tasks.
    `object_list` contains dicts of Asset (projects) properties (`id`, `name`, `uid`)
    or User (accounts) properties (`id`, `username`).

    Projects and accounts get in trash for `grace_period` and they are hard-deleted
    when their related schedule task run.
    We keep only username if `delete_all` equals False.
    """

    clocked_time = now() + timedelta(days=grace_period)
    clocked = ClockedSchedule.objects.create(clocked_time=clocked_time)

    (
        trash_model,
        fk_field_name,
        related_model,
        task,
        task_name_placeholder
    ) = _get_settings(trash_type, delete_all)

    if delete_all:
        # Delete any previous trash object if it belongs to this "delete all"
        # list because "delete all" supersedes deactivated status.
        obj_ids = [obj_dict['pk'] for obj_dict in objects_list]
        allowed_statuses = [TrashStatus.PENDING, TrashStatus.FAILED]
        trash_model.objects.filter(
            status__in=allowed_statuses,
            delete_all=False,
            **{f'{fk_field_name:}__in': obj_ids}
        ).delete()

    try:
        trash_objects = []
        audit_logs = []
        empty_manually = grace_period == -1

        for obj_dict in objects_list:
            trash_objects.append(
                trash_model(
                    request_author=request_author,
                    metadata=_get_metadata(obj_dict),
                    empty_manually=empty_manually,
                    delete_all=delete_all,
                    **{fk_field_name: obj_dict['pk']},
                )
            )
            audit_logs.append(
                AuditLog(
                    app_label=related_model._meta.app_label,
                    model_name=related_model._meta.model_name,
                    object_id=obj_dict['pk'],
                    user=request_author,
                    method=AuditMethod.IN_TRASH,
                    metadata=_get_metadata(obj_dict)
                )
            )

        trash_model.objects.bulk_create(trash_objects)

        periodic_tasks = PeriodicTask.objects.bulk_create(
            [
                PeriodicTask(
                    clocked=clocked,
                    name=task_name_placeholder.format(**ato.metadata),
                    task=f'kobo.apps.trash_bin.tasks.{task}',
                    args=json.dumps([ato.id]),
                    one_off=True,
                    enabled=not empty_manually,
                )
                for ato in trash_objects
            ],
        )

    except IntegrityError as e:
        raise TrashIntegrityError

    # Update relationships between periodic task and trash objects
    updated_trash_objects = []
    for idx, trash_object in enumerate(trash_objects):
        periodic_task = periodic_tasks[idx]
        assert periodic_task.args == json.dumps([trash_object.pk])
        trash_object.periodic_task = periodic_tasks[idx]
        updated_trash_objects.append(trash_object)

    trash_model.objects.bulk_update(
        updated_trash_objects, fields=['periodic_task_id']
    )

    AuditLog.objects.bulk_create(audit_logs)


@transaction.atomic()
def put_back(objects_list: list[dict], trash_type: str):

    trash_model, fk_field_name, *others = _get_settings(trash_type)

    obj_ids = [obj_dict['pk'] for obj_dict in objects_list]
    queryset = trash_model.objects.filter(
        status=TrashStatus.PENDING,
        **{f'{fk_field_name}__in': obj_ids}
    )
    periodic_task_ids = list(
        queryset.values_list('periodic_task_id', flat=True)
    )
    del_pto_results = queryset.delete()
    delete_model_key = f'{trash_model._meta.app_label}.{trash_model.__name__}'
    del_pto_count = del_pto_results[1].get(delete_model_key) or 0

    if del_pto_count != len(objects_list):
        raise TrashTaskInProgressError

    # Disconnect `PeriodicTasks` (plural) signal, until `PeriodicTask` (singular)
    # delete query finishes to avoid unnecessary DB queries.
    # see https://django-celery-beat.readthedocs.io/en/stable/reference/django-celery-beat.models.html#django_celery_beat.models.PeriodicTasks
    pre_delete.disconnect(PeriodicTasks.changed, sender=PeriodicTask)
    try:
        PeriodicTask.objects.only('pk').filter(pk__in=periodic_task_ids).delete()
    finally:
        pre_delete.connect(PeriodicTasks.changed, sender=PeriodicTask)

    # Force celery beat scheduler to refresh
    PeriodicTasks.update_changed()


def _delete_submissions(request_author: 'auth.User', asset: 'kpi.Asset'):
    stop = False
    (
        app_label,
        model_name,
    ) = asset.deployment.submission_model.get_app_label_and_model_name()

    while not stop:
        audit_logs = []
        submissions = list(asset.deployment.get_submissions(
            asset.owner, fields=['_id', '_uuid'], limit=200
        ))
        if not submissions:
            if not (
                submissions := asset.deployment.get_zombie_submissions()
            ):
                stop = True
                continue

        submission_ids = []
        for submission in submissions:
            audit_logs.append(AuditLog(
                app_label=app_label,
                model_name=model_name,
                object_id=submission['_id'],
                user=request_author,
                metadata={
                    'asset_uid': asset.uid,
                    'uuid': submission['_uuid'],
                }
            ))
            submission_ids.append(submission['_id'])

        json_response = asset.deployment.delete_submissions(
            {'submission_ids': submission_ids, 'query': ''}, request_author
        )

        # If requests has succeeded, let's log deletions (if any)
        if json_response['status'] == status.HTTP_200_OK and audit_logs:
            AuditLog.objects.bulk_create(audit_logs)


def _get_metadata(trashed_object: dict) -> dict:
    dict_copy = deepcopy(trashed_object)
    del dict_copy['pk']
    return dict_copy


def _get_settings(trash_type: str, delete_all: bool = False) -> tuple:
    if trash_type == 'asset':
        return (
            ProjectTrash,
            'asset_id',
            Asset,
            'empty_project',
            'Delete project {name} ({uid})',
        )

    if trash_type == 'user':
        return (
            AccountTrash,
            'user_id',
            get_user_model(),
            'empty_account',
            'Delete user’s account ({username})'
            if delete_all
            else 'Delete user’s data ({username})'
        )

    raise TrashNotImplementedError
