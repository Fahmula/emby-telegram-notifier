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
log_directory = os.path.join('log')
log_filename = os.path.join(log_directory, 'emby-telegram-notifier.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ensure the log directory exists
os.makedirs(log_directory, exist_ok=True)

# Create a handler for rotating log files daily
rotating_handler = TimedRotatingFileHandler(log_filename, when="midnight", interval=1, backupCount=7)
rotating_handler.setLevel(logging.INFO)
rotating_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(rotating_handler)

# Creating the directory structure if it doesn't exist
os.makedirs(os.path.join('data'), exist_ok=True)

# Creating the file path
notified_item_file = os.path.join('data', 'notified_item.json')


def send_telegram_notification(text, photo_id):
    base_photo_url = f"{EMBY_BASE_URL}/Items/{photo_id}/Images/Primary"

    try:
        image_response = requests.get(base_photo_url)
        image = ('photo.jpg', image_response.content, 'image/jpeg')

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": text,
            "parse_mode": "Markdown"
        }

        response = requests.post(url, data=data, files={'photo': image})

        return response

    except requests.RequestException as e:
        logging.error(f"Failed to send Telegram notification: {str(e)}")
        return None


def get_item_details(item_id):
    headers = {'accept': 'application/json'}
    params = {'api_key': EMBY_API_KEY}

    base_url = f"{EMBY_BASE_URL}/emby/Items"
    query_params = {
        'Recursive': 'true',
        'Fields': 'Overview,PremiereDate,ProviderIds,RemoteTrailers,ProductionYear,DateCreated',
        'Ids': item_id
    }

    try:
        response = requests.get(base_url, headers=headers, params={**params, **query_params})
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
        with open(notified_item_file, 'r') as file:
            notified_item_list = json.load(file)
            return set(notified_item_list)
    return set()


def save_notified_item(notified_item_to_save):
    with file_lock:
        with open(notified_item_file, 'w') as file:
            json.dump(list(notified_item_to_save), file)


notified_item = load_notified_item()


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


item_ids_to_process = []
file_lock = threading.Lock()


def process_payload(item_id):
    item_details = get_item_details(item_id)

    # Check if 'Overview' is empty
    if not item_details['Items'][0].get('Overview'):
        item_name = item_details['Items'][0].get('Name')
        logging.info(f'Waiting 60s for {item_name} metadata')
        time.sleep(60)
        item_details = get_item_details(item_id)

    item_type = item_details['Items'][0].get('Type', 'Unknown')
    item_name = item_details['Items'][0].get('Name', 'Unknown')
    release_year = item_details['Items'][0].get('ProductionYear', 'Unknown')
    premiere_date = item_details['Items'][0].get('PremiereDate', "0000-00-00T").split("T")[0]
    overview = item_details['Items'][0].get('Overview', 'Unknown')
    series_name = item_details['Items'][0].get('SeriesName', 'Unknown')
    series_id = item_details['Items'][0].get('SeriesId', 'Unknown')
    season_id = item_details['Items'][0].get('SeasonId', 'Unknown')
    season_epi = f"{item_details['Items'][0].get('IndexNumber', 'Unknown'):02}"
    season_num = f"{item_details['Items'][0].get('ParentIndexNumber', 'Unknown'):02}"
    season_name = f'Season {season_num}'

    if item_type == "Movie":

        if not item_already_notified(item_name, release_year):
            runtime_ticks = item_details['Items'][0].get('RunTimeTicks', 'Unknown')
            runtime_sec = runtime_ticks // 10_000_000
            hours, remainder = divmod(runtime_sec, 3600)
            minutes, seconds = divmod(remainder, 60)
            runtime = '{:02}:{:02}:{:02}'.format(hours, minutes, seconds)
            movie_name_cleaned = item_name.replace(f" ({release_year})", "").strip()
            trailer_url = item_details["Items"][0]["RemoteTrailers"][0].get('Url', 'Unknown')

            notification_message = (
                f"*🍿New Movie Added🍿*\n\n*{movie_name_cleaned}* *({release_year})*\n\n{overview}\n\n"
                f"Runtime\n{runtime}")

            if trailer_url:
                notification_message += f"\n\n[🎥]({trailer_url})[Trailer]({trailer_url})"

            send_telegram_notification(notification_message, item_id)

            mark_item_as_notified(item_name, release_year)
            logging.info(f"(Movie) {item_name} {release_year} notification was sent to Telegram!.")
            item_ids_to_process.remove(item_id)
            return "Movie notification was sent to Telegram"

        else:
            logging.info(f"(Movie) {item_name} Notification Was Already Sent")
            item_ids_to_process.remove(item_id)
            return "Notification Was Already Sent"

    if item_type == "Episode":

        series_name_cleaned = series_name.replace(f" ({release_year})", "").strip()
        season_details = get_item_details(season_id)
        season_date_created = season_details['Items'][0].get('DateCreated', "0000-00-00T").split("T")[0]
        season_overview = season_details['Items'][0].get('Overview', 'Unknown')
        series_details = get_item_details(series_id)
        series_overview = series_details['Items'][0].get('Overview', 'Unknown')
        episode_stored = f'{season_num}{season_epi}'

        # Check to see if it's a new season
        if (not item_already_notified(series_name_cleaned, season_name)
                and is_within_last_x_days(season_date_created, SEASON_ADDED_WITHIN_X_DAYS)):

            overview_to_use = series_overview if season_overview == 'Unknown' else season_overview

            notification_message = (
                f"*New Season Added*\n\n*{series_name_cleaned}* *({release_year})*\n\n"
                f"*Season* *{season_num}*\n\n{overview_to_use}\n\n"
            )

            send_telegram_notification(notification_message, season_id)

            mark_item_as_notified(series_name_cleaned, season_name)
            item_ids_to_process.remove(item_id)
            logging.info(f'(Season) {series_name_cleaned} '
                         f'Season {season_num} notification sent to Telegram!')
            return 'New Season Added'

        elif (not item_already_notified(series_name_cleaned, episode_stored)
              and not is_within_last_x_days(season_date_created, SEASON_ADDED_WITHIN_X_DAYS)):
            if is_within_last_x_days(premiere_date, EPISODE_PREMIERED_WITHIN_X_DAYS):

                notification_message = (
                    f"*New Episode Added*\n\n*Release Date*: {premiere_date}\n\n*Series*: {series_name_cleaned} *S*"
                    f"{season_num}*E*{season_epi}\n*Episode Title*: {item_name}\n\n{overview}\n\n"
                )
                response = send_telegram_notification(notification_message, season_id)

                if response:
                    mark_item_as_notified(series_name_cleaned, episode_stored)
                    item_ids_to_process.remove(item_id)
                    logging.info(f"(Episode) {series_name_cleaned} "
                                 f"S{season_num}E{season_epi} notification sent to Telegram!")
                    return "Notification sent to Telegram"
                else:
                    send_telegram_notification(notification_message, series_id)
                    logging.warning(f"(Episode) {series_name} season image does not exist, "
                                    f"falling back to series image")
                    mark_item_as_notified(series_name_cleaned, episode_stored)
                    item_ids_to_process.remove(item_id)
                    logging.info(f"(Episode) {series_name_cleaned} "
                                 f"S{season_num}E{season_epi} notification sent to Telegram!")
                    return "Notification sent to Telegram (fallback)"

            else:
                logging.info(f"(Episode) {series_name} S{season_num}E{season_epi} "
                             f"was premiered more than {EPISODE_PREMIERED_WITHIN_X_DAYS} days ago")
                item_ids_to_process.remove(item_id)
                return 'Premiered more than x days ago'

        else:
            logging.info(f"(Episode) {series_name} S{season_num}E{season_epi} Notification Was Already Sent")
            item_ids_to_process.remove(item_id)
            return 'Notification Was Already Sent'

    else:
        logging.error(f'Item type {item_type} not supported')
        item_ids_to_process.remove(item_id)
        return "Item type not supported."


@app.route('/webhook', methods=['POST'])
def emby_webhook():
    try:
        payload = json.loads(dict(request.form)['data'])
        item_id = payload['Item']['Id']

        if item_id not in item_ids_to_process:
            item_ids_to_process.append(item_id)

            # Start a new thread to process the payload with a 1-minute delay
            thread = threading.Thread(target=process_payload, args=(item_id,))
            thread.start()
            return "OK"
        return "OK"

    except HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
        return str(http_err)

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return f"Error: {str(e)}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
