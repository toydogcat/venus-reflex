import reflex as rx

config = rx.Config(
    app_name="venus_reflex",
    # Set the API URL to the machine's local IP so mobile devices can connect
    api_url="http://192.168.0.148:8003",
    theme=rx.theme(
        appearance="dark",
        accent_color="blue",
    ),
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ]
)
