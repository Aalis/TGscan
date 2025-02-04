from fastapi import FastAPI, HTTPException, Depends, status, Request, Form, Query
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from telethon import TelegramClient, functions, types
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from pydantic import BaseModel
from typing import List, Optional
import os
import asyncio
from math import ceil
from datetime import datetime, timedelta

app = FastAPI(title="Parser Pro Web")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Telegram API credentials
API_ID = 24051818
API_HASH = "a86f5da90e15c17c78e388003925b3a4"
BOT_TOKEN = os.getenv('BOT_TOKEN')  # You'll need to set this in .env

if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN in .env file. Get it from @BotFather on Telegram.")

# OAuth2 scheme for user authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class ParsingResult(BaseModel):
    users: List[dict]
    total_count: int

class CommentResult(BaseModel):
    comments: List[dict]
    total_count: int

# Create client instances
bot_client = None
user_client = None

# Store results in memory (in production, you'd want to use a proper database)
parsing_results = {}
comments_results = {}

async def get_bot_client():
    global bot_client
    if bot_client is None:
        bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        try:
            await bot_client.start(bot_token=BOT_TOKEN)
            print("Bot successfully authenticated!")
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
    if user_client is None:
        session_file = os.path.join(os.getcwd(), "telegram_session")
        user_client = TelegramClient(
            session_file,
            API_ID,
            API_HASH,
            device_model="Samsung Galaxy S20",
            system_version="Android 12",
            app_version="8.4.1",
            lang_code="en",
            system_lang_code="en"
        )
        try:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                print("User authentication required!")
                return None
            print("User successfully authenticated!")
        except Exception as e:
            print(f"Error starting user client: {str(e)}")
            raise
    return user_client

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
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/parse")
async def parse_form(request: Request):
    return templates.TemplateResponse("parse.html", {"request": request})

@app.post("/parse")
async def parse_chat_submit(
    request: Request,
    chat_id: str = Form(...),
    premium_only: bool = Form(False),
    with_phone: bool = Form(False),
    last_seen: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    client: TelegramClient = Depends(get_bot_client)  # Use bot client for user parsing
):
    try:
        print(f"Starting to parse chat: {chat_id}")
        # Get chat entity
        print("Getting chat entity...")
        entity = await client.get_entity(chat_id)
        print(f"Found chat: {entity.title if hasattr(entity, 'title') else chat_id}")
        
        # Initialize parameters for participant search
        offset = 0
        limit = 100
        all_participants = []
        total_processed = 0
        
        print("Starting to fetch members...")
        while True:
            print(f"Fetching members batch (offset: {offset}, limit: {limit})...")
            participants = await client(GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsSearch(''),
                offset=offset,
                limit=limit,
                hash=0
            ))
            
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
                
                # Apply filters
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
                "error": "No users found matching the specified criteria."
            })
        
        # Store results in memory with a unique ID
        result_id = len(parsing_results)
        results = {
            "users": all_participants,
            "total_count": len(all_participants)
        }
        parsing_results[result_id] = ParsingResult(**results)
        
        print(f"Parsing completed. Found {len(all_participants)} matching users.")
        # Redirect to results page
        return RedirectResponse(url=f"/results/{result_id}?page=1", status_code=303)
        
    except Exception as e:
        print(f"Error in parse_chat_submit: {str(e)}")  # Add debug logging
        return templates.TemplateResponse("parse.html", {
            "request": request,
            "error": str(e)
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
async def comments_form(request: Request):
    return templates.TemplateResponse("comments.html", {"request": request})

@app.post("/comments")
async def parse_comments_submit(
    request: Request,
    channel_id: str = Form(...),
    limit: int = Form(10),
    client: TelegramClient = Depends(get_user_client)
):
    if client is None:
        return templates.TemplateResponse("comments.html", {
            "request": request,
            "error": "User authentication required. Please run the script locally first to set up user session."
        })

    try:
        print(f"\nFetching comments from: {channel_id}")
        entity = await client.get_entity(channel_id)
        
        # Get channel messages first
        print(f"Fetching last {limit} posts...")
        messages = await client.get_messages(entity, limit=min(limit, 100))
        
        # Use a dictionary to store unique users by user_id
        unique_users = {}
        total_processed = 0
        
        for message in messages:
            try:
                if not message or not message.id:
                    continue
                    
                print(f"\nProcessing message ID: {message.id}")
                
                # Get post author info
                try:
                    post_author = await client.get_entity(message.from_id) if message.from_id else None
                    post_author_username = f"@{post_author.username}" if post_author and post_author.username else "Anonymous"
                except Exception as e:
                    post_author_username = "Unknown"
                    print(f"Error getting post author: {str(e)}")
                
                # Get all comments for this message
                comments = await client.get_messages(
                    entity,
                    reply_to=message.id,
                    limit=100
                )
                
                for comment in comments:
                    if not comment or not comment.from_id:
                        continue
                        
                    try:
                        # Get comment author info
                        author = await client.get_entity(comment.from_id)
                        
                        # Only add user if we haven't seen them before
                        if author.id not in unique_users:
                            comment_dict = {
                                'post_author': post_author_username,
                                'post_date': message.date.strftime("%Y-%m-%d %H:%M:%S"),
                                'post_text': message.text[:100] + "..." if len(message.text) > 100 else message.text,
                                'comment_id': comment.id,
                                'user_id': author.id,
                                'username': f"@{author.username}" if author.username else "No username",
                                'first_name': author.first_name,
                                'last_name': author.last_name if hasattr(author, 'last_name') else None,
                                'text': comment.text,
                                'date': comment.date.strftime("%Y-%m-%d %H:%M:%S"),
                                'reply_to': comment.reply_to_msg_id if hasattr(comment, 'reply_to_msg_id') else None,
                                'is_premium': author.premium if hasattr(author, 'premium') else False
                            }
                            unique_users[author.id] = comment_dict
                            total_processed += 1
                            print(f"Processed comment from {comment_dict['username']}")
                        
                    except Exception as e:
                        print(f"Error processing comment {comment.id}: {str(e)}")
                        continue
                        
            except Exception as e:
                print(f"Error processing message {message.id}: {str(e)}")
                continue
        
        # Convert dictionary values to list
        all_comments = list(unique_users.values())
        
        if not all_comments:
            return templates.TemplateResponse("comments.html", {
                "request": request,
                "error": f"No comments found in the last {limit} posts. Try increasing the number of posts to parse."
            })
        
        # Store results in memory with a unique ID
        result_id = len(comments_results)
        results = CommentResult(comments=all_comments, total_count=len(all_comments))
        comments_results[result_id] = results
        
        print(f"\nSuccessfully processed {len(all_comments)} unique users from {total_processed} total comments")
        
        # Redirect to results page
        return RedirectResponse(url=f"/comments_results/{result_id}?page=1", status_code=303)
        
    except Exception as e:
        print(f"Error in parse_comments_submit: {str(e)}")
        return templates.TemplateResponse("comments.html", {
            "request": request,
            "error": f"Error: {str(e)}\nPlease make sure the channel ID/username is correct and the channel is accessible."
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