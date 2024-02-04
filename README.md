# Emby Notification System

A simple Flask application that sends notifications to Telegram whenever new content (movies, series, seasons, episodes) is added to Emby.

---

## Features

- Sends Telegram notifications with media images whenever a new movie, series, season, or episode is added to Emby.
- Integrates with the Emby webhook plugin.
- Provides a filter to notify only for recent episodes or newly added seasons.

## Prerequisites

- An Emby server with the Webhook plugin installed.
- A Telegram bot token and chat ID (see the section on setting up a Telegram bot below).
- Docker (optional, for Docker installation).

## Installation

### Traditional Installation

1. Clone the repository.
2. Install the requirements using `pip install -r requirements.txt`.
3. Set up your environment variables. (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMBY_BASE_URL, EMBY_API_KEY, EPISODE_PREMIERED_WITHIN_X_DAYS, SEASON_ADDED_WITHIN_X_DAYS).
4. Run the application using `python3 app.py`.

### Docker Installation

If you have Docker and Docker Compose installed, you can use the provided `docker-compose.yml`

1. Set up your environment variables in a `.env` file.
2. Run `docker-compose up`.

## Setting Up a Telegram Bot

1. Start a Chat with BotFather on Telegram.
2. Send `/newbot` command.
3. Name your bot.
4. Choose a unique username for your bot; it must end in `bot`.
5. Retrieve your HTTP API token.
6. Get your chat ID by starting a chat with your bot, sending a message, then visiting `https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates` to find the chat ID in the returned JSON.
7. Input the Bot Token and Chat ID into the application's environment variables.

## Usage

### Setting up Emby Webhook

#### For Emby Server 4.7 or Lower:

1. Go to Emby settings.
2. Choose `Webhooks` and add a new webhook.
3. Set the server to the Flask application's endpoint (e.g., `http://localhost:5000/webhook`).
4. You can `Send Test Webhook` to make sure every is working so far.
5. Under `Library`, select `New Media Added`.
6. You can limit events to selected `Users`, but it's best to limit `Library` to `Movie & Shows`.

#### For Emby Server 4.8 or Higher:

1. Go to Emby settings.
2. Choose `Notification` and add a new notification.
3. Select `Webhooks` as the notification type.
4. Set the server to the Flask application's endpoint (e.g., `http://localhost:5000/webhook`).
5. You can set `Request content type` to either `multipart/form-data` or `application/json`.
6. You can `Send Test Webhook` to make sure every is working so far.
7. Under `Library`, select `New Media Added`.
8. You can limit events to selected `Users` and/or `Devices`, but it's best to limit `Library` to `Movie & Shows`.


#### Environment Variables Explanation:

- **`EPISODE_PREMIERED_WITHIN_X_DAYS`**:
  Determines how recent an episode's premiere date must be for a notification to be sent. For example, setting it to `7` means only episodes that premiered within the last 7 days will trigger a notification.

- **`SEASON_ADDED_WITHIN_X_DAYS`**:
  Dictates the threshold for sending notifications based on when a season was added to Emby. If set to `3`, then if a season was added within the last 3 days, episode notifications will not be sent to avoid potential spam from adding an entire season at once.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests for new features, bug fixes, or improvements.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
