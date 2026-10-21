from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.project import Project
from app.schemas.proxy import (
    ExposeRequest,
    ExposureContent,
    ProxyOverview,
    ServiceExposure,
    UnexposeRequest,
)
from app.services import docker_service, proxy_service, repo_service, settings_service

# Open to anyone who can edit a Compose file: the routes only change the editor's
# content, and saving it stays the normal validate, back up, write flow.
router = APIRouter(prefix="/api/proxy", tags=["proxy"])


def _project(project_id: str) -> Project:
    project = repo_service.find_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("", response_model=ProxyOverview)
def overview(db: Session = Depends(get_db)) -> ProxyOverview:
    values = settings_service.get_all(db)
    result = ProxyOverview(domain=values["proxy_domain"], network=values["proxy_network"])
    try:
        result.traefik = proxy_service.traefik_container()
        result.network_exists = docker_service.network_exists(result.network)
    except docker_service.DockerUnavailable:
        # The routes come from the files, so they still list.
        result.docker_available = False
    result.routes = proxy_service.routes(
        repo_service.attach_containers(repo_service.discover_projects())
    )
    return result


@router.post("/projects/{project_id}/services", response_model=list[ServiceExposure])
def project_services(project_id: str, body: ExposureContent) -> list[ServiceExposure]:
    _project(project_id)
    return proxy_service.services(body.content)


@router.post("/projects/{project_id}/expose", response_model=ExposureContent)
def expose(
    project_id: str, body: ExposeRequest, db: Session = Depends(get_db)
) -> ExposureContent:
    """The editor's content with the service exposed at `host`. Nothing is saved."""
    project = repo_service.attach_containers([_project(project_id)])[0]
    values = settings_service.get_all(db)
    host = proxy_service.full_host(body.host, values["proxy_domain"])
    for route in proxy_service.routes(
        [candidate for candidate in repo_service.discover_projects() if candidate.id != project.id]
    ):
        if host in route.hosts:
            raise HTTPException(
                status_code=409,
                detail=f"{host} is already used by {route.project_name}/{route.service}",
            )
    content = proxy_service.expose(
        body.content,
        project_name=repo_service.compose_project_name(project) or project.name,
        service=body.service,
        host=host,
        port=body.port,
        public=body.public,
        network=values["proxy_network"],
    )
    return ExposureContent(content=content)


@router.post("/projects/{project_id}/unexpose", response_model=ExposureContent)
def unexpose(
    project_id: str, body: UnexposeRequest, db: Session = Depends(get_db)
) -> ExposureContent:
    _project(project_id)
    network = settings_service.get_all(db)["proxy_network"]
    return ExposureContent(
        content=proxy_service.unexpose(body.content, service=body.service, network=network)
    )
