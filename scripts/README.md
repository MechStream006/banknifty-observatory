# scripts/ — Deployment and Operational Scripts

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review; production-touching scripts require sign-off

## Responsibility

Shell scripts for EC2 provisioning, deployment, backup, restore rehearsal, and one-off operational tasks. These are not application code — they are operational tools.

## What will live here

| Script | Purpose | When used |
|--------|---------|-----------|
| `setup_instance.sh` | EC2 first-boot provisioning | Once, on new instance |
| `deploy.sh` | Application deployment from repo | On each release |
| `backup_now.sh` | Manual backup trigger | On-demand |
| `restore_rehearsal.sh` | DR restore procedure into throwaway instance | Periodic, scheduled |
| `health_check.sh` | Quick platform health summary | Anytime |

## Safety rules

- Production scripts must be tested in a staging environment first.
- Destructive operations (database drops, volume wipes) are gated behind an explicit confirmation prompt.
- Scripts never hard-code secrets; they read from the same `BNO_` environment variables as the application.
