"""Finite recovery sweeps; the fast collector runs independently of this Dag."""
from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, task


@dag(dag_id='news_reconciliation',schedule='*/5 * * * *',
     start_date=datetime(2026,11,12,tzinfo=timezone.utc),catchup=False,
     max_active_runs=1,default_args={'retries':2,'retry_delay':timedelta(seconds=30)},
     dagrun_timeout=timedelta(minutes=15),is_paused_upon_creation=False)
def news_reconciliation():
    @task(execution_timeout=timedelta(minutes=10))
    def reconcile_recent_days():
        from news_ingestion import reconcile
        return reconcile(days=2,page_budget=100)
    reconcile_recent_days()


news_reconciliation()
