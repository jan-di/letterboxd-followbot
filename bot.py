import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram import (
    Update,
    User as TelegramUser,
    Chat as TelegramChat,
    ForceReply,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import dotenv

from letterboxd_followbot.database.model import (
    Base,
    User,
    Chat,
    FollowMember,
    FollowMemberType,
)
from letterboxd_followbot.letterboxd.api import LetterboxdClient
import logging

engine = create_engine("sqlite:///local.db")

Base.metadata.create_all(engine)

dotenv.load_dotenv()

FOLLOW_STATE_SEARCH_MEMBER, FOLLOW_STATE_CONFIRM = range(2)


def create_or_update_user(telegram_user: TelegramUser):
    user_id = telegram_user.id

    with Session(engine) as session:
        user = session.get(User, user_id)

        if user is None:
            user = User(id=user_id)
            session.add(user)

        user.first_name = telegram_user.first_name
        user.last_name = telegram_user.last_name
        user.username = telegram_user.username
        user.language_code = telegram_user.language_code
        session.commit()

    return user


def create_or_update_chat(telegram_chat: TelegramChat):
    chat_id = telegram_chat.id

    with Session(engine) as session:
        chat = session.get(Chat, chat_id)

        if chat is None:
            chat = Chat(id=chat_id)
            session.add(chat)

        chat.type = telegram_chat.type
        if telegram_chat.type == "private":
            chat.title = f"{telegram_chat.first_name} {telegram_chat.last_name}"
        elif telegram_chat.type in ("group", "supergroup"):
            chat.title = telegram_chat.title
        session.commit()

    return chat


async def follow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    user = create_or_update_user(update.effective_user)
    chat = create_or_update_chat(update.effective_chat)

    await update.message.reply_text(
        f"Please enter name of the member or a link to the member you want to follow. Send /cancel to stop.",
        reply_markup=ForceReply(selective=True),
    )

    return FOLLOW_STATE_SEARCH_MEMBER


async def follow_search_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    member_name = update.message.text

    results = letterboxd_client.search(member_name, include=["MemberSearchItem"])

    member_count = len(results["items"])
    if member_count == 0:
        await update.message.reply_text(
            "No members found. Please try again",
            reply_markup=ForceReply(selective=True),
        )
        return FOLLOW_STATE_SEARCH_MEMBER
    elif member_count > 1:
        text = "Found {} members.\n{".format(member_count)

        for member in results["items"]:
            member = member["member"]
            text += "\n{} ({})".format(member["displayName"], member["username"])

        text += "\nPlease specify your query."

        await update.message.reply_text(text, reply_markup=ForceReply(selective=True))
        return FOLLOW_STATE_SEARCH_MEMBER

    member = results["items"][0]["member"]

    biggest_avatar = len(member["avatar"]["sizes"]) - 1
    avatar_url = member["avatar"]["sizes"][biggest_avatar]["url"]
    caption = f"Follow {member['displayName']} ({member['username']})?"
    context.user_data["member_id"] = member["id"]

    reply_keyboard = ReplyKeyboardMarkup(
        [["Yes", "No"]], one_time_keyboard=True, selective=True
    )

    await update.message.reply_photo(
        avatar_url, caption=caption, reply_markup=reply_keyboard
    )

    return FOLLOW_STATE_CONFIRM


async def follow_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    member_id = context.user_data["member_id"]

    message = update.message.text
    if message == "No":
        await update.message.reply_text("Okay, please search again")
        return FOLLOW_STATE_SEARCH_MEMBER

    await update.message.reply_text(f"Following member with id {member_id}")

    with Session(engine) as session:
        chat_id = update.effective_chat.id

        follow_member = FollowMember(
            chat_id=chat_id, member_id=member_id, type=FollowMemberType.MEMBER
        )
        session.add(follow_member)

        session.commit()

    return ConversationHandler.END


async def follow_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(f"Joo dann halt nicht")

    return ConversationHandler.END


async def unfollow_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with Session(engine) as session:
        chat_id = update.effective_chat.id

        follow_members = session.query(FollowMember).filter_by(chat_id=chat_id).all()

        for follow_member in follow_members:
            session.delete(follow_member)

        session.commit()

    await update.message.reply_text("Unfollowed all members")


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TG_TOKEN).build()

    LETTERBOXD_CLIENT_ID = os.environ.get("LETTERBOXD_CLIENT_ID")
    LETTERBOXD_CLIENT_SECRET = os.environ.get("LETTERBOXD_CLIENT_SECRET")
    letterboxd_client = LetterboxdClient(LETTERBOXD_CLIENT_ID, LETTERBOXD_CLIENT_SECRET)

    # results = letterboxd_client.search("jantast", include=["MemberSearchItem"])
    # print(results)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("follow", follow_start)],
        states={
            FOLLOW_STATE_SEARCH_MEMBER: [
                MessageHandler(filters.Regex("^(.*)$"), follow_search_member)
            ],
            FOLLOW_STATE_CONFIRM: [
                MessageHandler(filters.Regex("^(Yes|No)$"), follow_confirm)
            ],
            # PHOTO: [
            #     MessageHandler(filters.PHOTO, photo),
            #     CommandHandler("skip", skip_photo),
            # ],
            # LOCATION: [
            #     MessageHandler(filters.LOCATION, location),
            #     CommandHandler("skip", skip_location),
            # ],
            # BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio)],
        },
        fallbacks=[CommandHandler("cancel", follow_cancel)],
    )
    unfollow = CommandHandler("unfollowall", unfollow_all)
    app.add_handler(unfollow)
    app.add_handler(conv_handler)

    logging.info("Starting bot")

    

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
