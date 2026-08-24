# 04 — DAG delivery and per-task runtime

**What to build:** A DAG that lives in the pipeline's own image reaches the scheduler and
runs one real task on the cluster, with declared pod resources and credentials from a
cluster Secret. This is the platform seam proved on a trivial graph before the real one
depends on it. It replaces the map's ticket 1 ("deployment shape"), which the cloud
effort's spec already owns down to the executor, the metadata database and remote
logging — implementing both documents' version would produce two Helm value sets.

**Blocked by:** None in this tracker. **External precondition:** the cloud effort's
Airflow install (KubernetesExecutor, metadata database, remote task logs). If it is not
there, this ticket waits on it — it must not install a second Airflow.

**Status:** ready-for-agent

- [ ] DAG code ships inside the one git-sha-tagged image every pipeline pod runs: no git-sync sidecar, no separate DAG volume, so DAG and code are the same version by construction
- [ ] A DAG in that image is picked up by the scheduler and one task pod runs an existing make target to completion
- [ ] That task's pod declares CPU and memory requests taken from the cloud effort's stage-placement and capacity numbers; no capacity number is invented here
- [ ] The task reads its object-store credentials from the cluster Secret bound to its ServiceAccount; nothing is baked into the image
- [ ] No stage runs on the scheduler pod — a stage implemented as a callable inside the DAG file is a defect, not a shortcut
- [ ] The external precondition is verified before any DAG work, and recorded
