# Disports

A Discord client built for Ubuntu Touch.

> [!IMPORTANT]
> Using any unofficial Discord client is against Discord's [Terms of Service](https://discord.com/terms) and may result in your account being restricted or permanently banned. **Use Disports at your own risk.**

## Installation

Disports can currently be installed on your Ubuntu Touch device via the artifact in GitHub Actions, or by building it yourself using [Clickable](https://clickable-ut.dev).

## Logging In

### QR Code Login (Recommended)

This is the safest and easiest way to sign in. It works just like scanning a QR code in the official Discord client.

1. Open Disports and tap **Login with QR Code**.
2. A QR code will appear on screen.
3. On an Android or iOS device, open Discord and go to:
   **User Settings -> Scan QR Code**
4. Point your camera at the QR code shown in Disports.
5. Confirm the login on your device - you're in!

### Token Login (Not Recommended)

> [!WARNING]
> Token login is strongly discouraged. Your token is essentially your password - sharing or exposing it can compromise your account. It also means two devices will share the same session, which Discord may flag as suspicious. Only use this method if QR code login isn't an option for you.

If you still need to use token login, here's how to find your token:

1. Open [Discord](https://discord.com/app) in a desktop browser and log in.
2. Press <kbd>F12</kbd> to open the browser's developer tools.
3. Go to the **Network** tab, then press <kbd>F5</kbd> to reload the page.
4. In the filter/search box, type `discord api`.
5. Click on any request that appears, and look in the **Request Headers** section.
6. Find the `Authorization` header - its value is your token.
7. Copy it, paste it into the Token field in Disports, and tap **Login**.

## Warnings

- **Terms of Service** - Discord does not officially support third-party clients. Using Disports may violate Discord's Terms of Service and could lead to your account being restricted or banned. Disports tries to behave as closely to the official client as possible to minimise this risk, but no guarantees can be made.

- **Token security** - If you use token login, treat your token like a password. Never share it with anyone or paste it into websites or apps you don't trust.

- **No affiliation** - Disports is an independent project and is not affiliated with, endorsed by, or supported by Discord Inc.
