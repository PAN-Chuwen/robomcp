"""/v1 routes. Every lookup is filtered by the caller's org; other orgs' rows are reported as 404."""

from __future__ import annotations

import uuid
from typing import Annotated, TypeVar

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from robomcp_platform import queue, results
from robomcp_platform.api.deps import PrincipalDep, SessionDep
from robomcp_platform.api.schemas import (
    AgentVersionCreate,
    AgentVersionOut,
    EpisodeOut,
    EpisodePage,
    ExperimentCreate,
    ExperimentOut,
    MeOut,
    ProjectCreate,
    ProjectOut,
    SuiteVersionCreate,
    SuiteVersionOut,
)
from robomcp_platform.hashing import content_hash
from robomcp_platform.models import (
    EPISODE_STATUSES,
    AgentVersion,
    Episode,
    Experiment,
    Organization,
    Project,
    Suite,
    SuiteVersion,
    User,
)

router = APIRouter()
M = TypeVar("M")


def _scoped(session, model: type[M], obj_id: uuid.UUID, org_id: uuid.UUID, *, lock: bool = False) -> M:
    stmt = select(model).where(model.id == obj_id, model.org_id == org_id)  # type: ignore[attr-defined]
    obj = session.scalar(stmt.with_for_update() if lock else stmt)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__tablename__.rstrip('s')} not found")  # type: ignore[attr-defined]
    return obj


@router.get("/me", response_model=MeOut)
def me(session: SessionDep, p: PrincipalDep) -> MeOut:
    org = session.get_one(Organization, p.org_id)
    user = session.get_one(User, p.user_id)
    return MeOut(org_id=org.id, org_name=org.name, org_slug=org.slug, user_id=user.id, email=user.email,
                 role=p.role, api_key_prefix=p.api_key_prefix)


# --- projects -------------------------------------------------------------------------------------------


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: SessionDep, p: PrincipalDep) -> Project:
    if session.scalar(select(Project.id).where(Project.org_id == p.org_id, Project.name == body.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "a project with this name already exists")
    project = Project(org_id=p.org_id, name=body.name)
    session.add(project)
    session.commit()
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: SessionDep, p: PrincipalDep) -> list[Project]:
    return list(session.scalars(select(Project).where(Project.org_id == p.org_id).order_by(Project.created_at)))


# --- immutable versions ---------------------------------------------------------------------------------


@router.post("/projects/{project_id}/suites/{suite_name}/versions", response_model=SuiteVersionOut,
             status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "identical tasks already exist; that version is returned"}})
def create_suite_version(
    project_id: uuid.UUID,
    suite_name: Annotated[str, Path(min_length=1, max_length=200)],
    body: SuiteVersionCreate,
    session: SessionDep,
    p: PrincipalDep,
    response: Response,
) -> SuiteVersionOut:
    project = _scoped(session, Project, project_id, p.org_id)
    session.execute(
        pg_insert(Suite)
        .values(id=uuid.uuid4(), org_id=p.org_id, project_id=project.id, name=suite_name)
        .on_conflict_do_nothing(index_elements=["project_id", "name"])
    )
    # Lock the suite so concurrent creates get consecutive version numbers.
    suite = session.scalars(
        select(Suite).where(Suite.project_id == project.id, Suite.name == suite_name).with_for_update()
    ).one()
    tasks = [t.model_dump(exclude_unset=True) for t in body.tasks]
    digest = content_hash(tasks)
    version = session.scalar(
        select(SuiteVersion).where(SuiteVersion.suite_id == suite.id, SuiteVersion.content_hash == digest)
    )
    if version is None:
        latest = session.scalar(select(func.max(SuiteVersion.version)).where(SuiteVersion.suite_id == suite.id))
        version = SuiteVersion(org_id=p.org_id, suite_id=suite.id, version=(latest or 0) + 1, tasks=tasks,
                               content_hash=digest)
        session.add(version)
        session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return SuiteVersionOut(
        id=version.id, suite_id=suite.id, suite_name=suite.name, version=version.version,
        content_hash=version.content_hash, tasks=version.tasks, created_at=version.created_at,
    )


@router.post("/projects/{project_id}/agent-versions", response_model=AgentVersionOut,
             status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "identical config already exists under this name; it is returned"}})
def create_agent_version(
    project_id: uuid.UUID, body: AgentVersionCreate, session: SessionDep, p: PrincipalDep, response: Response
) -> AgentVersion:
    # Lock the project so concurrent creates under one name get consecutive version numbers.
    project = _scoped(session, Project, project_id, p.org_id, lock=True)
    digest = content_hash(body.config)
    existing = session.scalar(
        select(AgentVersion).where(AgentVersion.project_id == project.id, AgentVersion.name == body.name,
                                   AgentVersion.content_hash == digest)
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    latest = session.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.project_id == project.id,
                                                     AgentVersion.name == body.name)
    )
    agent = AgentVersion(org_id=p.org_id, project_id=project.id, name=body.name, version=(latest or 0) + 1,
                         config=body.config, content_hash=digest)
    session.add(agent)
    session.commit()
    return agent


# --- experiments ----------------------------------------------------------------------------------------


def _experiment_out(session, experiment: Experiment) -> ExperimentOut:
    data = {c: getattr(experiment, c) for c in ExperimentOut.model_fields if c != "results"}
    return ExperimentOut(**data, results=results.summarize(session, experiment.id))


@router.post("/experiments", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
def create_experiment(body: ExperimentCreate, request: Request, session: SessionDep, p: PrincipalDep) -> ExperimentOut:
    project = _scoped(session, Project, body.project_id, p.org_id)
    suite_version = _scoped(session, SuiteVersion, body.suite_version_id, p.org_id)
    agent_version = _scoped(session, AgentVersion, body.agent_version_id, p.org_id)
    if session.get_one(Suite, suite_version.suite_id).project_id != project.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "suite version belongs to another project")
    if agent_version.project_id != project.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent version belongs to another project")

    n = len(suite_version.tasks) * len(body.seeds) * body.repeats
    cap = request.app.state.settings.max_episodes_per_experiment
    if n > cap:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{n} episodes exceeds the limit of {cap}")

    experiment = Experiment(org_id=p.org_id, project_id=project.id, suite_version_id=suite_version.id,
                            agent_version_id=agent_version.id, name=body.name, seeds=body.seeds,
                            repeats=body.repeats, status="queued")
    session.add(experiment)
    session.flush()
    queue.expand_episodes(session, experiment, [t["key"] for t in suite_version.tasks])
    session.commit()
    return _experiment_out(session, experiment)


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: uuid.UUID, session: SessionDep, p: PrincipalDep) -> ExperimentOut:
    return _experiment_out(session, _scoped(session, Experiment, experiment_id, p.org_id))


@router.get("/experiments/{experiment_id}/episodes", response_model=EpisodePage)
def list_episodes(
    experiment_id: uuid.UUID,
    session: SessionDep,
    p: PrincipalDep,
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(" + "|".join(EPISODE_STATUSES) + ")$")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EpisodePage:
    experiment = _scoped(session, Experiment, experiment_id, p.org_id)
    where = [Episode.experiment_id == experiment.id, Episode.org_id == p.org_id]
    if status_filter:
        where.append(Episode.status == status_filter)
    total = session.scalar(select(func.count()).select_from(Episode).where(*where)) or 0
    items = session.scalars(
        select(Episode).where(*where)
        .order_by(Episode.task_key, Episode.seed, Episode.repeat_index).limit(limit).offset(offset)
    ).all()
    return EpisodePage(items=[EpisodeOut.model_validate(e) for e in items], total=total, limit=limit, offset=offset)
