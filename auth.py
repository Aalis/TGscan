from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneNumberBannedError, PhoneNumberInvalidError, PhoneCodeInvalidError
import asyncio
import datetime
import logging
import time
import os
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.orm import Session
from datetime import timedelta
import models
import schemas
from database import get_db
from security import (
    verify_password,
    get_password_hash,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_active_user
)

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('telegram_client.log'),
        logging.StreamHandler(sys.stdout)
    ],
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Telegram API credentials
API_ID = 24051818
API_HASH = "a86f5da90e15c17c78e388003925b3a4"

async def handle_rate_limit(e: FloodWaitError):
    """Handle rate limit by waiting the required time"""
    wait_time = e.seconds
    wait_delta = datetime.timedelta(seconds=wait_time)
    
    print("\n" + "="*50)
    print("🚫 RATE LIMIT DETECTED! 🚫")
    print("="*50)
    print(f"Telegram says: You must wait {wait_delta} before trying again")
    print(f"Current time: {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"You can try again at: {(datetime.datetime.now() + wait_delta).strftime('%H:%M:%S')}")
    print("="*50 + "\n")
    
    logger.warning(f"Rate limit reached! Must wait for {wait_delta}")
    await asyncio.sleep(wait_time)
    return True

async def main():
    start_time = datetime.datetime.now()
    logger.info(f"Script started at {start_time}")
    
    # Use current directory for session file
    session_file = os.path.join(os.getcwd(), "telegram_session")
    logger.info(f"Using session file: {session_file}")
    
    # Debug info
    print("\n🔍 Debug Information:")
    print(f"API ID: {API_ID}")
    print(f"API Hash: {API_HASH[:4]}...{API_HASH[-4:]}")
    print(f"Session file: {session_file}")
    print(f"Start time: {start_time}")
    
    # Initialize the Telegram client with mobile device info
    print("\n🔄 Initializing client...")
    logger.info("Creating TelegramClient instance with custom device info")
    client = TelegramClient(
        session_file,
        API_ID,
        API_HASH,
        device_model="Samsung Galaxy S20",
        system_version="Android 12",
        app_version="8.4.1",
        lang_code="en",
        system_lang_code="en",
        connection_retries=None
    )
    
    try:
        print("\n🔄 Connecting to Telegram...")
        logger.info("Attempting to connect to Telegram servers")
        connection_start = datetime.datetime.now()
        await client.connect()
        connection_time = datetime.datetime.now() - connection_start
        logger.info(f"Connection attempt took {connection_time.total_seconds():.2f} seconds")
        
        if not client.is_connected():
            logger.error("Failed to connect to Telegram servers")
            print("\n❌ ERROR: Could not connect to Telegram servers!")
            return
            
        logger.info("Successfully connected to Telegram servers")
        print("✅ Connected to Telegram servers")

        # Check if already authorized
        logger.info("Checking authorization status")
        auth_status = await client.is_user_authorized()
        logger.debug(f"Authorization status: {auth_status}")
        
        if not auth_status:
            logger.info("Not authorized, starting sign in process")
            try:
                print("\n🔑 Starting authentication process...")
                phone = input("\n📱 Enter your phone number (e.g., +1234567890): ")
                
                # Request the code with more detailed error handling
                print("\n📤 Requesting verification code...")
                logger.info(f"Sending code request to {phone}")
                try:
                    code_request_start = datetime.datetime.now()
                    sent = await client.send_code_request(
                        phone,
                        force_sms=False
                    )
                    code_request_time = datetime.datetime.now() - code_request_start
                    logger.info(f"Code request took {code_request_time.total_seconds():.2f} seconds")
                    
                    print("\nℹ️ Code request details:")
                    print(f"Phone code hash: {sent.phone_code_hash[:4]}...")
                    print(f"Next type: {sent.next_type}")
                    print(f"Timeout: {sent.timeout} seconds")
                    
                except Exception as e:
                    logger.error(f"Failed to send code request: {str(e)}", exc_info=True)
                    print(f"\n❌ Detailed error during code request: {str(e)}")
                    print("Error type:", type(e).__name__)
                    raise
                
                print("\n✅ Code request sent!")
                logger.info("Code request sent successfully")
                print("\nPlease check:")
                print("1. Your Telegram app for the login code")
                print("2. SMS messages on your phone")
                print("3. Make sure your phone has internet connection")
                print("4. Check if Telegram app shows login attempt")
                
                code = input("\nEnter the code when you receive it (or Ctrl+C to cancel): ")
                if not code:
                    logger.warning("No code entered by user")
                    print("Please enter a valid code")
                    return
                
                logger.info("Attempting to sign in with provided code")
                print("\n🔄 Verifying code...")
                sign_in_start = datetime.datetime.now()
                
                try:
                    await client.sign_in(phone, code)
                    sign_in_time = datetime.datetime.now() - sign_in_start
                    logger.info(f"Sign in completed in {sign_in_time.total_seconds():.2f} seconds")
                    print("✅ Code verified successfully!")
                except SessionPasswordNeededError:
                    print("\n2FA is enabled. Please enter your password:")
                    password = input("Password: ")
                    await client.sign_in(password=password)
                    print("✅ Successfully authenticated with 2FA!")
                
            except FloodWaitError as e:
                await handle_rate_limit(e)
                return
                
            except PhoneNumberBannedError:
                logger.error(f"Phone number {phone} is banned from Telegram")
                print("\n❌ ERROR: This phone number is banned from Telegram!")
                print("Please use a different phone number.")
                return
                
            except PhoneNumberInvalidError:
                logger.error(f"Invalid phone number format: {phone}")
                print("\n❌ ERROR: Invalid phone number format!")
                print("Please use international format like +1234567890")
                return
                
            except Exception as e:
                logger.error(f"Authentication error: {str(e)}", exc_info=True)
                print(f"\n❌ Error during authentication: {str(e)}")
                print("Error type:", type(e).__name__)
                print("\nPlease check:")
                print("1. Your internet connection")
                print("2. Your API credentials")
                print("3. Your phone number format")
                return

        # Get user info
        logger.info("Fetching user information")
        me = await client.get_me()
        print(f"\n✅ Signed in as: {me.first_name} (@{me.username if me.username else 'no username'})")
        logger.info(f"Successfully signed in as {me.username if me.username else me.id}")
        
        # Save the session for future use
        print("\n💾 Saving session...")
        if os.path.exists(session_file):
            print(f"✅ Session saved to: {session_file}")
            print("\nYou can now use this session for parsing comments!")

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        print(f"\n❌ Unexpected error: {str(e)}")
        raise

    finally:
        # Disconnect from the Telegram servers
        logger.info("Disconnecting from Telegram servers")
        await client.disconnect()
        logger.info("Disconnected from Telegram servers")
        
        end_time = datetime.datetime.now()
        total_time = end_time - start_time
        logger.info(f"Script finished at {end_time}")
        logger.info(f"Total execution time: {total_time.total_seconds():.2f} seconds")

if __name__ == "__main__":
    try:
        logger.info("Starting main coroutine")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript interrupted by user")
        logger.info("Script interrupted by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
        logger.error(f"Fatal error: {str(e)}", exc_info=True)

router = APIRouter(tags=["authentication"])

@router.post("/register", response_model=schemas.User)
async def register(
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        # Debug logging
        print(f"Received registration request:")
        print(f"- Email: {email}")
        print(f"- Username: {username}")
        print(f"- Password length: {len(password)}")
        
        # Basic validation
        if not email or not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All fields are required"
            )
        
        # Email validation
        if '@' not in email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )
        
        # Username validation
        if not username or username.lower() in ['undefined', 'null', '']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid username"
            )
        
        # Check existing email
        if db.query(models.User).filter(models.User.email == email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check existing username
        if db.query(models.User).filter(models.User.username == username).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        
        # Create user
        hashed_password = get_password_hash(password)
        new_user = models.User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            is_active=True
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        print(f"User created successfully:")
        print(f"- ID: {new_user.id}")
        print(f"- Username: {new_user.username}")
        
        return new_user
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"Error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during registration"
        )

@router.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Find user by email
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "username": user.username}, 
        expires_delta=access_token_expires
    )
    
    # Return token and user info
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "username": user.username
        }
    }

@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    return current_user

@router.get("/me/files", response_model=schemas.UserWithFiles)
async def read_user_files(current_user: models.User = Depends(get_current_active_user)):
    return current_user

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(current_user: models.User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Delete the currently logged in user"""
    # Delete the user from the database
    db.delete(current_user)
    db.commit()
    return None