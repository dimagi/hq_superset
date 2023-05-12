import os
from superset.extensions import celery_app

import logging
from .utils import AsyncImportHelper

logger = logging.getLogger(__name__)


@celery_app.task(name='refresh_hq_datasource_task')
def refresh_hq_datasource_task(domain, datasource_id, display_name, export_path, datasource_defn, user_id):
    from .views import refresh_hq_datasource
    try:
        refresh_hq_datasource(domain, datasource_id, display_name, export_path, datasource_defn, user_id)
    except Exception:
        AsyncImportHelper(domain, datasource_id).mark_as_complete()
        os.remove(export_path)
        raise
