import os
import time
import json
import requests
import threading
import logging
from requests.exceptions import HTTPError
from flask import Flask, request
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
EMBY_BASE_URL = os.environ.get("EMBY_BASE_URL")
EMBY_API_KEY = os.environ.get("EMBY_API_KEY")
EPISODE_PREMIERED_WITHIN_X_DAYS = int(os.environ.get("EPISODE_PREMIERED_WITHIN_X_DAYS"))
SEASON_ADDED_WITHIN_X_DAYS = int(os.environ.get("SEASON_ADDED_WITHIN_X_DAYS"))

# Set up logging
log_directory = os.path.join("log")
log_filename = os.path.join(log_directory, "emby-telegram-notifier.log")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Ensure the log directory exists
os.makedirs(log_directory, exist_ok=True)

# Create a handler for rotating log files daily
rotating_handler = TimedRotatingFileHandler(
    log_filename, when="midnight", interval=1, backupCount=7
)
rotating_handler.setLevel(logging.INFO)
rotating_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logging.getLogger().addHandler(rotating_handler)

# Creating the directory structure if it doesn't exist
os.makedirs(os.path.join("data"), exist_ok=True)

# Creating the file path
notified_item_file = os.path.join("data", "notified_item.json")

file_lock = threading.Lock()


def send_telegram_notification(text, photo_id):
    base_photo_url = (
        f"{EMBY_BASE_URL}/Items/{photo_id}/Images/Primary" if photo_id else None
    )

    try:
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": text, "parse_mode": "Markdown"}

        if photo_id:
            image_response = requests.get(base_photo_url)
            image = ("photo.jpg", image_response.content, "image/jpeg")
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            response = requests.post(url, data=data, files={"photo": image})
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data["text"] = text
            response = requests.post(url, data=data)

        return response

    except requests.RequestException as e:
        logging.error(f"Failed to send Telegram notification: {str(e)}")
        return None


def get_item_details(item_id):
    headers = {"accept": "application/json"}
    params = {"api_key": EMBY_API_KEY}

    base_url = f"{EMBY_BASE_URL}/emby/Items"
    query_params = {
        "Recursive": "true",
        "Fields": "Overview,PremiereDate,ProviderIds,RemoteTrailers,ProductionYear,DateCreated",
        "Ids": item_id,
    }

    try:
        response = requests.get(
            base_url, headers=headers, params={**params, **query_params}
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException as e:
        logging.error(f"Failed to retrieve item details: {str(e)}")
        return None


def is_within_last_x_days(date_str, x):
    days_ago = datetime.now() - timedelta(days=x)
    return date_str >= days_ago.isoformat()


def load_notified_item():
    if os.path.exists(notified_item_file):
        with open(notified_item_file, "r") as file:
            notified_item_list = json.load(file)
            return set(notified_item_list)
    return set()


notified_item = load_notified_item()


def save_notified_item(notified_item_to_save):
    with file_lock:
        with open(notified_item_file, "w") as file:
            json.dump(list(notified_item_to_save), file)


def item_already_notified(item_name, release_year):
    key = f"{item_name} {release_year}"
    return key in notified_item


def mark_item_as_notified(item_name, release_year, max_entries=100):
    key = f"{item_name} {release_year}"
    notified_item.add(key)

    if len(notified_item) > max_entries:
        oldest_key = notified_item.pop()  # Removes and returns the oldest item
        logging.info(f"Key '{oldest_key}' has been deleted from notified_Item")

    save_notified_item(notified_item)


def process_payload(item_id):
    item_details = get_item_details(item_id)

    # Check if 'Overview' is empty every 60s, with a timeout of 5 minutes
    timeout_seconds = 300
    start_time = time.time()

    if not item_details["Items"][0].get("Overview"):
        while True:
            elapsed_time = time.time() - start_time
            item_name = item_details["Items"][0].get("Name")
            item_type = item_details["Items"][0].get("Type", "Unknown")

            # Check if elapsed time exceeds the timeout
            if elapsed_time >= timeout_seconds:
                if item_type == "Movie":
                    logging.warning(f"Timed out waiting for {item_name} metadata")
                else:
                    # Assuming the item type is "Episode" if it's not "Movie"
                    series_name = item_details["Items"][0].get("SeriesName", "Unknown")
                    season_epi = (
                        f"{item_details['Items'][0].get('IndexNumber', 'Unknown'):02}"
                    )
                    season_num = f"{item_details['Items'][0].get('ParentIndexNumber', 'Unknown'):02}"
                    logging.warning(
                        f"Timed out waiting for {series_name} S{season_num}E{season_epi} metadata"
                    )
                break

            # Check if it's a movie or episode
            if item_type == "Movie":
                logging.info(f"Waiting 60s for {item_name} metadata")
            else:
                series_name = item_details["Items"][0].get("SeriesName", "Unknown")
                season_epi = (
                    f"{item_details['Items'][0].get('IndexNumber', 'Unknown'):02}"
                )
                season_num = (
                    f"{item_details['Items'][0].get('ParentIndexNumber', 'Unknown'):02}"
                )
                logging.info(
                    f"Waiting 60s for {series_name} S{season_num}E{season_epi} metadata"
                )

            time.sleep(60)
            item_details = get_item_details(item_id)

            if item_details["Items"][0].get("Overview"):
                break

    item_type = item_details["Items"][0].get("Type", "Unknown")
    item_name = item_details["Items"][0].get("Name", "Unknown")
    release_year = item_details["Items"][0].get("ProductionYear", "Unknown")
    premiere_date = (
        item_details["Items"][0].get("PremiereDate", "0000-00-00T").split("T")[0]
    )
    overview = item_details["Items"][0].get("Overview", "Unknown")
    series_name = item_details["Items"][0].get("SeriesName", "Unknown")
    series_id = item_details["Items"][0].get("SeriesId", "Unknown")
    season_id = item_details["Items"][0].get("SeasonId", "Unknown")
    season_epi = f"{item_details['Items'][0].get('IndexNumber', 'Unknown'):02}"
    season_num = f"{item_details['Items'][0].get('ParentIndexNumber', 'Unknown'):02}"
    season_name = f"Season {season_num}"

    if item_type == "Movie":
        if not item_already_notified(item_name, release_year):
            runtime_ticks = item_details["Items"][0].get("RunTimeTicks", "Unknown")
            runtime_sec = runtime_ticks // 10_000_000
            hours, remainder = divmod(runtime_sec, 3600)
            minutes, seconds = divmod(remainder, 60)
            runtime = "{:02}:{:02}:{:02}".format(hours, minutes, seconds)
            movie_name_cleaned = item_name.replace(f" ({release_year})", "").strip()
            trailer_url = "Unknown"

            if (
                "RemoteTrailers" in item_details["Items"][0]
                and item_details["Items"][0]["RemoteTrailers"]
            ):
                trailer_url = item_details["Items"][0]["RemoteTrailers"][0].get(
                    "Url", "Unknown"
                )

            notification_message = (
                f"*🍿New Movie Added🍿*\n\n*{movie_name_cleaned}* *({release_year})*\n\n{overview}\n\n"
                f"Runtime\n{runtime}"
            )

            if trailer_url != "Unknown":
                notification_message += (
                    f"\n\n[🎥]({trailer_url})[Trailer]({trailer_url})"
                )

            mark_item_as_notified(item_name, release_year)

            send_telegram_notification(notification_message, item_id)

            logging.info(
                f"(Movie) {item_name} {release_year} notification was sent to Telegram!."
            )
            return "Movie notification was sent to Telegram"

        else:
            logging.info(f"(Movie) {item_name} Notification Was Already Sent")
            return "Notification Was Already Sent"

    if item_type == "Episode":
        series_name_cleaned = series_name.replace(f" ({release_year})", "").strip()
        season_details = get_item_details(season_id)
        season_date_created = (
            season_details["Items"][0].get("DateCreated", "0000-00-00T").split("T")[0]
        )
        season_overview = season_details["Items"][0].get("Overview", "Unknown")
        series_details = get_item_details(series_id)
        series_overview = series_details["Items"][0].get("Overview", "Unknown")
        episode_stored = f"S{season_num}E{season_epi}"

        # Check to see if it's a new season
        if not item_already_notified(
            series_name_cleaned, season_name
        ) and is_within_last_x_days(season_date_created, SEASON_ADDED_WITHIN_X_DAYS):
            overview_to_use = (
                series_overview if season_overview == "Unknown" else season_overview
            )

            notification_message = (
                f"*New Season Added*\n\n*{series_name_cleaned}* *({release_year})*\n\n"
                f"*Season* *{season_num}*\n\n{overview_to_use}\n\n"
            )

            mark_item_as_notified(series_name_cleaned, season_name)

            send_telegram_notification(notification_message, season_id)

            logging.info(
                f"(Season) {series_name_cleaned} "
                f"Season {season_num} notification sent to Telegram!"
            )
            return "New Season Added"

        elif not item_already_notified(
            series_name_cleaned, episode_stored
        ) and not is_within_last_x_days(
            season_date_created, SEASON_ADDED_WITHIN_X_DAYS
        ):
            if is_within_last_x_days(premiere_date, EPISODE_PREMIERED_WITHIN_X_DAYS):
                notification_message = (
                    f"*New Episode Added*\n\n*Release Date*: {premiere_date}\n\n*Series*: {series_name_cleaned} *S*"
                    f"{season_num}*E*{season_epi}\n*Episode Title*: {item_name}\n\n{overview}\n\n"
                )

                mark_item_as_notified(series_name_cleaned, episode_stored)

                response = send_telegram_notification(notification_message, season_id)

                if response:
                    logging.info(
                        f"(Episode) {series_name_cleaned} "
                        f"S{season_num}E{season_epi} notification sent to Telegram!"
                    )
                    return "Notification sent to Telegram"
                else:
                    mark_item_as_notified(series_name_cleaned, episode_stored)

                    send_telegram_notification(notification_message, series_id)

                    logging.warning(
                        f"(Episode) {series_name} season image does not exist, "
                        f"falling back to series image"
                    )
                    logging.info(
                        f"(Episode) {series_name_cleaned} "
                        f"S{season_num}E{season_epi} notification sent to Telegram!"
                    )
                    return "Notification sent to Telegram (fallback)"

            else:
                logging.info(
                    f"(Episode) {series_name} S{season_num}E{season_epi} "
                    f"was premiered more than {EPISODE_PREMIERED_WITHIN_X_DAYS} days ago"
                )
                return "Premiered more than x days ago"

        else:
            logging.info(
                f"(Episode) {series_name} S{season_num}E{season_epi} Notification Was Already Sent"
            )
            return "Notification Was Already Sent"

    else:
        logging.error(f"Item type {item_type} not supported")
        return "Item type not supported."


@app.route("/webhook", methods=["POST"])
def emby_webhook():
    try:
        # Try the first method
        payload = json.loads(dict(request.form)["data"])
    except KeyError:
        try:
            # Try the second method
            payload = json.loads(request.data)
        except json.JSONDecodeError as json_err:
            logging.error(f"JSON decoding error: {json_err}")
            return "Error: Invalid JSON format", 400
        except Exception as e:
            logging.error(f"Error during payload processing: {str(e)}")
            return f"Error: {str(e)}", 500
    except json.JSONDecodeError as json_err:
        logging.error(f"JSON decoding error: {json_err}")
        return "Error: Invalid JSON format", 400
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return f"Error: {str(e)}", 500

    # Check if payload is sample webhook
    if payload["Title"] == "Test Notification":
        server_name = payload["Server"]["Name"]
        version = payload["Server"]["Version"]
        notification_message = (
            f"Success!\n\n*Server Name*: {server_name}\n\n*Server Version*: {version}"
        )
        send_telegram_notification(notification_message, None)
        return "OK"

    try:
        item_id = payload["Item"]["Id"]

        # Start a new thread to process the payload with a 1-minute delay
        thread = threading.Thread(target=process_payload, args=(item_id,))
        thread.start()
        return "OK"

    except KeyError as key_err:
        logging.error(f"Key error occurred: {key_err}")
        return f"Error: {str(key_err)}", 400

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return f"Error: {str(e)}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
