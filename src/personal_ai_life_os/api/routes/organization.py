"""Owner-scoped tags, collections, and item organization."""

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    CollectionCreateRequest,
    CollectionResponse,
    CollectionUpdateRequest,
    ItemOrganizationResponse,
    ItemOrganizationUpdateRequest,
    TagCreateRequest,
    TagResponse,
    TagUpdateRequest,
)
from personal_ai_life_os.models import Collection, SourceConnection, SourceItem, Tag

router = APIRouter(tags=["organization"])


def _tag_or_404(session: SessionDep, owner_id: str, tag_id: str) -> Tag:
    tag = session.scalar(select(Tag).where(Tag.id == tag_id, Tag.owner_id == owner_id))
    if tag is None:
        raise HTTPException(status_code=404, detail={"code": "tag_not_found", "message": "The selected tag was not found."})
    return tag


def _collection_or_404(session: SessionDep, owner_id: str, collection_id: str) -> Collection:
    collection = session.scalar(
        select(Collection).where(Collection.id == collection_id, Collection.owner_id == owner_id)
    )
    if collection is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "collection_not_found", "message": "The selected collection was not found."},
        )
    return collection


def _item_or_404(session: SessionDep, owner_id: str, item_id: str) -> SourceItem:
    item = session.scalar(
        select(SourceItem)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(
            SourceItem.id == item_id,
            SourceItem.owner_id == owner_id,
            SourceItem.deleted_at.is_(None),
            SourceItem.is_current.is_(True),
            SourceConnection.status != "deleting",
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "item_not_found", "message": "The selected item was not found."})
    return item


@router.get("/tags", response_model=list[TagResponse])
def list_tags(user: CurrentUserDep, session: SessionDep) -> list[Tag]:
    return list(session.scalars(select(Tag).where(Tag.owner_id == user.id).order_by(Tag.name_key, Tag.id)))


@router.post("/tags", response_model=TagResponse, status_code=201)
def create_tag(payload: TagCreateRequest, user: CurrentUserDep, session: SessionDep) -> Tag:
    tag = Tag(
        owner_id=user.id,
        name=payload.name,
        name_key=payload.name.casefold(),
        color=payload.color,
    )
    session.add(tag)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail={"code": "tag_exists", "message": "A tag with this name already exists."}) from error
    session.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=TagResponse)
def update_tag(tag_id: str, payload: TagUpdateRequest, user: CurrentUserDep, session: SessionDep) -> Tag:
    tag = _tag_or_404(session, user.id, tag_id)
    if payload.name is not None:
        tag.name = payload.name
        tag.name_key = payload.name.casefold()
    if payload.clear_color:
        tag.color = None
    elif payload.color is not None:
        tag.color = payload.color
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail={"code": "tag_exists", "message": "A tag with this name already exists."}) from error
    session.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: str, user: CurrentUserDep, session: SessionDep) -> Response:
    tag = _tag_or_404(session, user.id, tag_id)
    session.delete(tag)
    session.commit()
    return Response(status_code=204)


@router.get("/collections", response_model=list[CollectionResponse])
def list_collections(user: CurrentUserDep, session: SessionDep) -> list[Collection]:
    return list(
        session.scalars(
            select(Collection).where(Collection.owner_id == user.id).order_by(Collection.name_key, Collection.id)
        )
    )


@router.post("/collections", response_model=CollectionResponse, status_code=201)
def create_collection(
    payload: CollectionCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> Collection:
    collection = Collection(
        owner_id=user.id,
        name=payload.name,
        name_key=payload.name.casefold(),
        description=payload.description,
    )
    session.add(collection)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "collection_exists", "message": "A collection with this name already exists."},
        ) from error
    session.refresh(collection)
    return collection


@router.patch("/collections/{collection_id}", response_model=CollectionResponse)
def update_collection(
    collection_id: str,
    payload: CollectionUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> Collection:
    collection = _collection_or_404(session, user.id, collection_id)
    if payload.name is not None:
        collection.name = payload.name
        collection.name_key = payload.name.casefold()
    if payload.clear_description:
        collection.description = None
    elif payload.description is not None:
        collection.description = payload.description
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "collection_exists", "message": "A collection with this name already exists."},
        ) from error
    session.refresh(collection)
    return collection


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: str, user: CurrentUserDep, session: SessionDep) -> Response:
    collection = _collection_or_404(session, user.id, collection_id)
    session.delete(collection)
    session.commit()
    return Response(status_code=204)


@router.get("/items/{item_id}/organization", response_model=ItemOrganizationResponse)
def get_item_organization(item_id: str, user: CurrentUserDep, session: SessionDep) -> dict:
    item = _item_or_404(session, user.id, item_id)
    return {
        "item_id": item.id,
        "tags": [TagResponse.model_validate(tag) for tag in sorted(item.tags, key=lambda tag: tag.name_key)],
        "collections": [
            CollectionResponse.model_validate(collection)
            for collection in sorted(item.collections, key=lambda collection: collection.name_key)
        ],
    }


@router.put("/items/{item_id}/organization", response_model=ItemOrganizationResponse)
def update_item_organization(
    item_id: str,
    payload: ItemOrganizationUpdateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    item = _item_or_404(session, user.id, item_id)
    tags = list(
        session.scalars(
            select(Tag).where(Tag.owner_id == user.id, Tag.id.in_(payload.tag_ids))
        )
    )
    collections = list(
        session.scalars(
            select(Collection).where(
                Collection.owner_id == user.id,
                Collection.id.in_(payload.collection_ids),
            )
        )
    )
    if len(tags) != len(payload.tag_ids) or len(collections) != len(payload.collection_ids):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_organization_ids", "message": "Every tag and collection must belong to this account."},
        )
    item.tags = tags
    item.collections = collections
    session.commit()
    session.refresh(item)
    return {
        "item_id": item.id,
        "tags": [TagResponse.model_validate(tag) for tag in sorted(item.tags, key=lambda tag: tag.name_key)],
        "collections": [
            CollectionResponse.model_validate(collection)
            for collection in sorted(item.collections, key=lambda collection: collection.name_key)
        ],
    }
