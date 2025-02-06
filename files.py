from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.orm import Session
import models
import schemas
from database import get_db
from security import get_current_active_user
import json
import os
from datetime import datetime
from typing import List
from fastapi.requests import Request
from fastapi.templating import Jinja2Templates
from math import ceil

router = APIRouter(tags=["files"])

# Create directory for saved files if it doesn't exist
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

templates = Jinja2Templates(directory="templates")

@router.post("/files/", response_model=schemas.SavedFile)
async def create_file(
    file_data: schemas.SavedFileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    # Create unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{current_user.id}_{timestamp}_{file_data.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # Create database record
    db_file = models.SavedFile(
        **file_data.dict(),
        file_path=file_path,
        owner_id=current_user.id
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file

@router.get("/files/", response_model=List[schemas.SavedFile])
async def list_files(
    skip: int = 0,
    limit: int = 50,
    sort: str = Query(None, regex="^(date_asc|date_desc|name_asc|name_desc)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    query = db.query(models.SavedFile).filter(models.SavedFile.owner_id == current_user.id)
    
    # Apply sorting
    if sort == "date_desc":
        query = query.order_by(models.SavedFile.created_at.desc())
    elif sort == "date_asc":
        query = query.order_by(models.SavedFile.created_at.asc())
    elif sort == "name_asc":
        query = query.order_by(models.SavedFile.filename.asc())
    elif sort == "name_desc":
        query = query.order_by(models.SavedFile.filename.desc())
    else:
        # Default sorting
        query = query.order_by(models.SavedFile.created_at.desc())
    
    files = query.offset(skip).limit(limit).all()
    return files

@router.get("/files/{file_id}", response_model=schemas.SavedFile)
async def get_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    file = db.query(models.SavedFile)\
        .filter(models.SavedFile.id == file_id)\
        .filter(models.SavedFile.owner_id == current_user.id)\
        .first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return file

@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    file = db.query(models.SavedFile)\
        .filter(models.SavedFile.id == file_id)\
        .filter(models.SavedFile.owner_id == current_user.id)\
        .first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Delete physical file if it exists
    if os.path.exists(file.file_path):
        os.remove(file.file_path)
    
    # Delete database record
    db.delete(file)
    db.commit()
    return {"message": "File deleted successfully"}

@router.get("/files/{file_id}/view")
async def view_file(
    file_id: int,
    request: Request,
    page: int = Query(1, ge=1),  # Add page parameter with default value 1
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    try:
        print(f"Viewing file {file_id} for user {current_user.username}, page {page}")
        
        # Get file metadata
        file = db.query(models.SavedFile)\
            .filter(models.SavedFile.id == file_id)\
            .filter(models.SavedFile.owner_id == current_user.id)\
            .first()
            
        if not file:
            print(f"File {file_id} not found for user {current_user.username}")
            raise HTTPException(status_code=404, detail="File not found")
            
        # Read file contents
        try:
            with open(file.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading file {file.file_path}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error reading file: {str(e)}"
            )
            
        # Calculate pagination
        items_per_page = 100
        total_items = len(data)
        total_pages = max(1, ceil(total_items / items_per_page))
        current_page = min(max(1, page), total_pages)
        start_idx = (current_page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
            
        # Return appropriate template based on file type
        template_data = {
            "request": request,
            "user": current_user,
            "is_authenticated": True,
            "file_id": file_id
        }
        
        if file.file_type == 'chat':
            template_data.update({
                "results": {
                    "users": data,
                    "total_count": total_items
                },
                "page_users": data[start_idx:end_idx],
                "current_page": current_page,
                "total_pages": total_pages
            })
            return templates.TemplateResponse("results.html", template_data)
        else:
            template_data.update({
                "comments": data,
                "page_comments": data[start_idx:end_idx],
                "current_page": current_page,
                "total_pages": total_pages,
                "total_count": total_items
            })
            return templates.TemplateResponse("comments_results.html", template_data)
            
    except HTTPException as he:
        print(f"HTTP Exception in view_file: {str(he)}")
        if he.status_code == 401:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Please log in to view results"
            }, status_code=401)
        raise he
    except Exception as e:
        print(f"Error viewing file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error viewing file: {str(e)}"
        ) 