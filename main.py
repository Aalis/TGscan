from fastapi import FastAPI, HTTPException, Depends, status, Request, Form, Query
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from telethon import TelegramClient, functions, types
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.errors import FloodWaitError
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import asyncio
from math import ceil
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import uuid

# Load environment variables
load_dotenv()

import models
import schemas
from database import engine, get_db
from security import get_current_active_user
import auth
import files

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="TGscan")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth.router, prefix="/auth")
app.include_router(files.router, prefix="/api")

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Please set API_ID, API_HASH and BOT_TOKEN in .env file")

# OAuth2 scheme for user authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

class ParsingResult(BaseModel):
    users: List[dict]
    total_count: int

class CommentResult(BaseModel):
    comments: List[dict]
    total_count: int

# Create client instances with retry logic
bot_client = None
user_client = None

# Store results in memory (temporary, will be moved to database)
parsing_results = {}
comments_results = {}

async def handle_rate_limit(e: FloodWaitError):
    """Handle rate limit by waiting the required time"""
    wait_time = e.seconds
    print(f"\n🚫 Rate limit hit! Must wait {wait_time} seconds")
    print(f"Current time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Can retry at: {(datetime.now() + timedelta(seconds=wait_time)).strftime('%H:%M:%S')}")
    await asyncio.sleep(wait_time)

async def get_bot_client():
    global bot_client
    if bot_client is None or not bot_client.is_connected():
        bot_client = TelegramClient('bot_session', API_ID, API_HASH, retry_delay=1, auto_reconnect=True)
        try:
            await bot_client.start(bot_token=BOT_TOKEN)
            print("Bot successfully authenticated!")
        except FloodWaitError as e:
            await handle_rate_limit(e)
            await bot_client.start(bot_token=BOT_TOKEN)
        except Exception as e:
            print(f"Error starting bot: {str(e)}")
            raise
    
    try:
        yield bot_client
    except Exception as e:
        print(f"Error in bot client operation: {str(e)}")
        raise

async def get_user_client():
    global user_client
    try:
        if user_client is None or not user_client.is_connected():
            session_file = os.path.join(os.getcwd(), "telegram_session")
            user_client = TelegramClient(
                session_file,
                API_ID,
                API_HASH,
                device_model="Samsung Galaxy S20",
                system_version="Android 12",
                app_version="8.4.1",
                lang_code="en",
                system_lang_code="en",
                retry_delay=1,
                auto_reconnect=True
            )
            
            print("\nInitializing user client...")
            await user_client.connect()
            
            if not await user_client.is_user_authorized():
                print("User not authorized - please run the auth.py script first to authenticate")
                raise HTTPException(
                    status_code=401,
                    detail="Telegram user authentication required. Please run the auth.py script first."
                )
                
            print("User client successfully authenticated!")
            
        return user_client
    except FloodWaitError as e:
        await handle_rate_limit(e)
        return await get_user_client()
    except Exception as e:
        print(f"Error in get_user_client: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize Telegram client: {str(e)}"
        )

def format_last_seen(timestamp):
    if not timestamp:
        return None
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    diff = now - dt
    
    if diff < timedelta(hours=1):
        return f"{diff.seconds // 60} minutes ago"
    elif diff < timedelta(days=1):
        return f"{diff.seconds // 3600} hours ago"
    else:
        return dt.strftime("%Y-%m-%d %H:%M")

@app.on_event("shutdown")
async def shutdown_event():
    global bot_client, user_client
    if bot_client:
        await bot_client.disconnect()
    if user_client:
        await user_client.disconnect()

@app.get("/")
async def home(request: Request):
    try:
        token = request.cookies.get("access_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
        if token:
            try:
                # Verify token and get user
                user = await get_current_active_user(token)
                return templates.TemplateResponse("index.html", {
                    "request": request,
                    "is_authenticated": True,
                    "user": user
                })
            except:
                pass
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "is_authenticated": False
        })
    except Exception as e:
        print(f"Error in home route: {str(e)}")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "is_authenticated": False
        })

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/parse")
async def parse_form(
    request: Request,
    current_user: models.User = Depends(get_current_active_user)
):
    try:
        # Log authentication attempt
        print(f"User {current_user.username} accessing parse form")
        
        # Return the template with user info
        return templates.TemplateResponse("parse.html", {
            "request": request,
            "user": current_user,
            "is_authenticated": True
        })
    except HTTPException as he:
        print(f"HTTP Exception in parse_form: {str(he)}")
        if he.status_code == 401:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Please log in to access this page"
            })
        raise he
    except Exception as e:
        print(f"Error in parse_form: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading parse form: {str(e)}"
        )

@app.post("/parse")
async def parse_chat_submit(
    request: Request,
    chat_id: str = Form(...),
    premium_only: bool = Form(False),
    with_phone: bool = Form(False),
    last_seen: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        print(f"Starting to parse chat: {chat_id}")
        
        # Get user client
        client = await get_user_client()
        if not client:
            return templates.TemplateResponse("parse.html", {
                "request": request,
                "error": "Telegram authentication required. Please run the auth.py script first.",
                "user": current_user
            })
            
        try:
            entity = await client.get_entity(chat_id)
        except FloodWaitError as e:
            await handle_rate_limit(e)
            entity = await client.get_entity(chat_id)
            
        print(f"Found chat: {entity.title if hasattr(entity, 'title') else chat_id}")
        
        offset = 0
        limit = 100
        all_participants = []
        total_processed = 0
        
        print("Starting to fetch members...")
        while True:
            try:
                print(f"Fetching members batch (offset: {offset}, limit: {limit})...")
                participants = await client(GetParticipantsRequest(
                    channel=entity,
                    filter=ChannelParticipantsSearch(''),
                    offset=offset,
                    limit=limit,
                    hash=0
                ))
            except FloodWaitError as e:
                await handle_rate_limit(e)
                continue
                
            if not participants.users:
                break
            
            print(f"Processing {len(participants.users)} users...")
            for user in participants.users:
                last_seen_timestamp = getattr(user.status, 'was_online', None) if hasattr(user, 'status') else None
                
                user_dict = {
                    'id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'premium': user.premium,
                    'phone': user.phone if hasattr(user, 'phone') else None,
                    'last_seen': format_last_seen(last_seen_timestamp)
                }
                
                if premium_only and not user.premium:
                    continue
                if with_phone and not user.phone:
                    continue
                if last_seen and last_seen_timestamp:
                    hours_ago = (datetime.now() - datetime.fromtimestamp(last_seen_timestamp)).total_seconds() / 3600
                    if hours_ago > last_seen:
                        continue
                    
                all_participants.append(user_dict)
                total_processed += 1
            
            print(f"Total users processed: {total_processed}")
            offset += len(participants.users)
            if len(participants.users) < limit:
                break

        print("Finalizing results...")
        if not all_participants:
            return templates.TemplateResponse("parse.html", {
                "request": request,
                "error": "No users found matching the specified criteria.",
                "user": current_user
            })
        
        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chat_members_{timestamp}.json"
        file_path = os.path.join(files.UPLOAD_DIR, f"{current_user.id}_{filename}")
        
        # Save the file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(all_participants, f, ensure_ascii=False, indent=2)
        
        # Create database record
        file_data = schemas.SavedFileCreate(
            filename=filename,
            file_type='chat',
            source_id=str(entity.id),
            source_name=entity.title if hasattr(entity, 'title') else chat_id,
            file_metadata=json.dumps({
                'total_users': len(all_participants),
                'filters': {
                    'premium_only': premium_only,
                    'with_phone': with_phone,
                    'last_seen': last_seen,
                    'gender': gender
                }
            })
        )
        
        db_file = models.SavedFile(
            **file_data.dict(),
            file_path=file_path,
            owner_id=current_user.id
        )
        db.add(db_file)
        db.commit()
        
        print(f"Parsing completed. Found {len(all_participants)} matching users.")
        return RedirectResponse(url=f"/api/files/{db_file.id}/view", status_code=303)
        
    except Exception as e:
        print(f"Error in parse_chat_submit: {str(e)}")
        return templates.TemplateResponse("parse.html", {
            "request": request,
            "error": str(e),
            "user": current_user
        })

@app.get("/results/{result_id}")
async def show_results(
    request: Request,
    result_id: int,
    page: int = Query(1, ge=1)
):
    try:
        results = parsing_results.get(result_id)
        if not results:
            return RedirectResponse(url="/parse", status_code=303)
        
        # Calculate pagination
        items_per_page = 100
        total_items = len(results.users)
        total_pages = max(1, ceil(total_items / items_per_page))
        current_page = min(max(1, page), total_pages)
        
        start_idx = (current_page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        page_users = results.users[start_idx:end_idx]
        
        # Convert ParsingResult to dict for JSON serialization
        results_dict = {
            "users": results.users,
            "total_count": results.total_count
        }
        
        return templates.TemplateResponse("results.html", {
            "request": request,
            "results": results_dict,
            "page_users": page_users,
            "current_page": current_page,
            "total_pages": total_pages
        })
        
    except Exception as e:
        print(f"Error in show_results: {str(e)}")  # Add debug logging
        return templates.TemplateResponse("results.html", {
            "request": request,
            "error": str(e)
        })

@app.get("/comments")
async def comments_form(
    request: Request,
    current_user: models.User = Depends(get_current_active_user)
):
    try:
        # Log authentication attempt
        print(f"User {current_user.username} accessing comments form")
        
        # Return the template with user info
        return templates.TemplateResponse("comments.html", {
            "request": request,
            "user": current_user,
            "is_authenticated": True
        })
    except HTTPException as he:
        print(f"HTTP Exception in comments_form: {str(he)}")
        if he.status_code == 401:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Please log in to access this page"
            })
        raise he
    except Exception as e:
        print(f"Error in comments_form: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading comments form: {str(e)}"
        )

@app.post("/comments")
async def parse_comments(
    request: Request,
    chat_id: str = Form(...),
    message_limit: Optional[int] = Form(None),
    client: TelegramClient = Depends(get_user_client),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        print(f"\n{'='*50}")
        print(f"Starting to parse comments from chat: {chat_id}")
        print(f"Requested message limit: {message_limit}")
        print(f"User: {current_user.username}")
        print(f"{'='*50}\n")

        try:
            print("Attempting to get entity...")
            entity = await client.get_entity(chat_id)
            print(f"Successfully got entity: {entity.id} ({entity.title if hasattr(entity, 'title') else chat_id})")
        except FloodWaitError as e:
            await handle_rate_limit(e)
            entity = await client.get_entity(chat_id)

        # Initialize storage for unique users
        unique_users = {}
        total_messages = 0
        total_comments = 0

        # Process messages in batches
        offset_id = 0
        limit = min(100, message_limit) if message_limit else 100

        print("\nStarting message fetch loop...")
        while True:
            try:
                print(f"Fetching messages batch (offset_id: {offset_id}, limit: {limit})...")
                messages = await client.get_messages(entity, limit=limit, offset_id=offset_id)

                if not messages:
                    print("No more messages found")
                    break

                print(f"Fetched {len(messages)} messages")
                total_messages += len(messages)

                # Process each message's comments
                for msg in messages:
                    if msg.replies and msg.replies.replies > 0:
                        print(f"Processing message {msg.id} with {msg.replies.replies} replies...")
                        try:
                            replies = await client.get_messages(
                                entity,
                                reply_to=msg.id,
                                limit=100
                            )
                            print(f"Fetched {len(replies)} replies for message {msg.id}")

                            for reply in replies:
                                if not reply.sender:
                                    continue

                                total_comments += 1
                                user_id = reply.sender.id

                                if user_id not in unique_users:
                                    try:
                                        user = await client.get_entity(user_id)
                                        last_seen_timestamp = getattr(user.status, 'was_online', None) if hasattr(user, 'status') else None

                                        unique_users[user_id] = {
                                            'id': user.id,
                                            'username': user.username,
                                            'first_name': user.first_name,
                                            'last_name': user.last_name,
                                            'premium': getattr(user, 'premium', False),
                                            'phone': getattr(user, 'phone', None),
                                            'last_seen': format_last_seen(last_seen_timestamp),
                                            'comment_count': 1,
                                            'last_comment_date': reply.date.isoformat()
                                        }
                                        print(f"Added new user: {user.username or user.id}")
                                    except Exception as e:
                                        print(f"Error getting user info: {str(e)}")
                                        continue
                                else:
                                    unique_users[user_id]['comment_count'] += 1
                                    if reply.date > datetime.fromisoformat(unique_users[user_id]['last_comment_date']):
                                        unique_users[user_id]['last_comment_date'] = reply.date.isoformat()

                        except FloodWaitError as e:
                            await handle_rate_limit(e)
                            continue
                        except Exception as e:
                            print(f"Error processing replies for message {msg.id}: {str(e)}")
                            continue

                if message_limit and total_messages >= message_limit:
                    print(f"Reached message limit of {message_limit}")
                    break

                offset_id = messages[-1].id

            except FloodWaitError as e:
                await handle_rate_limit(e)
                continue
            except Exception as e:
                print(f"Error fetching messages: {str(e)}")
                break

        # Convert unique_users dict to list
        users_list = list(unique_users.values())
        total_users = len(users_list)

        print(f"\n{'='*50}")
        print(f"Processing completed:")
        print(f"Total messages processed: {total_messages}")
        print(f"Total comments found: {total_comments}")
        print(f"Total unique commenters: {total_users}")
        print(f"{'='*50}\n")

        if not users_list:
            return templates.TemplateResponse("comments.html", {
                "request": request,
                "error": "No comments found in the specified number of messages.",
                "user": current_user
            })

        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"commenters_{timestamp}.json"
        file_path = os.path.join(files.UPLOAD_DIR, f"{current_user.id}_{filename}")

        # Save the file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(users_list, f, ensure_ascii=False, indent=2)

        # Create database record
        file_data = schemas.SavedFileCreate(
            filename=filename,
            file_type='comments',
            source_id=str(entity.id),
            source_name=entity.title if hasattr(entity, 'title') else chat_id,
            file_metadata=json.dumps({
                'total_users': total_users,
                'total_comments': total_comments,
                'messages_processed': total_messages,
                'message_limit': message_limit
            })
        )

        db_file = models.SavedFile(
            **file_data.dict(),
            file_path=file_path,
            owner_id=current_user.id
        )
        db.add(db_file)
        db.commit()

        print(f"Results saved to file: {file_path}")
        return RedirectResponse(url=f"/api/files/{db_file.id}/view", status_code=303)

    except Exception as e:
        print(f"Error in parse_comments: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return templates.TemplateResponse("comments.html", {
            "request": request,
            "error": str(e),
            "user": current_user
        })

@app.get("/comments_results/{result_id}")
async def show_comments_results(
    request: Request,
    result_id: int,
    page: int = Query(1, ge=1)
):
    try:
        results = comments_results.get(result_id)
        if not results:
            return RedirectResponse(url="/comments", status_code=303)
        
        # Calculate pagination
        items_per_page = 100
        total_items = len(results.comments)
        total_pages = max(1, ceil(total_items / items_per_page))
        current_page = min(max(1, page), total_pages)
        
        start_idx = (current_page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        page_comments = results.comments[start_idx:end_idx]
        
        # Convert user IDs to strings to avoid concatenation issues
        for comment in page_comments:
            comment['user_id'] = str(comment['user_id'])
        
        return templates.TemplateResponse("comments_results.html", {
            "request": request,
            "comments": results.comments,
            "page_comments": page_comments,
            "current_page": current_page,
            "total_pages": total_pages,
            "total_count": results.total_count
        })
        
    except Exception as e:
        print(f"Error in show_comments_results: {str(e)}")
        return templates.TemplateResponse("comments_results.html", {
            "request": request,
            "error": str(e)
        })

@app.get("/dashboard")
async def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort: str = Query(None, regex="^(date_asc|date_desc|name_asc|name_desc)$"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    try:
        # Log authentication attempt
        print(f"User {current_user.username} accessing dashboard")
        
        # Get total count of files
        query = db.query(models.SavedFile)\
            .filter(models.SavedFile.owner_id == current_user.id)
            
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
        
        total_files = query.count()
        
        # Calculate pagination
        total_pages = max(1, ceil(total_files / limit))
        current_page = min(max(1, page), total_pages)
        skip = (current_page - 1) * limit
        
        # Get files for current page
        files = query.offset(skip).limit(limit).all()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "files": files,
            "page": current_page,
            "total_pages": total_pages,
            "user": current_user,
            "is_authenticated": True
        })
    except HTTPException as he:
        print(f"HTTP Exception in dashboard: {str(he)}")
        if he.status_code == 401:
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "Please log in to access the dashboard"
            }, status_code=401)
        raise he
    except Exception as e:
        print(f"Error in dashboard: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        ) 