"""Cluster-Module der DAG-Executor-Facade (D1-Zerlegung, S2/B).

Die Facade ``backend.workflow_dag_runner.default_agent_node_executor`` bleibt
aus Kompatibilitaetsgruenden am alten Ort und delegiert schrittweise hierher.
Wichtig (S3): Diese Module binden KEINE Namen aus ``workflow_dag_runner`` zur
Importzeit. Benoetigte Abhaengigkeiten (Kanban-Sync, Dispatcher) werden von der
Facade zur **Aufrufzeit** als Callables uebergeben. Sonst wuerden die 7
``patch("backend.workflow_dag_runner._update_kanban_task_status")``-Punkte ins
Leere greifen und es entstuende ein Importzyklus.
"""
