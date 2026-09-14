def fetch_profile(provider, client , token):
    if provider == "google":
        info = token.get("userinfo") or client.userinfo(token=token)
        return{
            "provider" : "google",
            "provider_user_id" : info["sub"],
            "email" : info.get("email"),
            "name" : info.get("name") or info.get("email"),
            "avatar_url" : info.get("picture"),
        }

    if provider == "github":
        user = client.get("user", token=token).json()
        email = user.get("email")
        if not email:
            emails = client.get("user/emails", token=token).json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")), None
            )
            email = primary["email"] if primary else None
        return {
            "provider" : "github",
            "provider_user_id" : str(user["id"]),
            "email" : email,
            "name" : user.get("name") or user.get("login"),
            "avatar_url" : user.get("avatar_url"),
        }

    if provider == "discord":
        user = client.get("users/@me", token=token).json()
        avatar = user.get("avatar")
        return {
            "provider" : "discord",
            "provider_user_id" : str(user["id"]),
            "email" : user.get("email"),
            "name" : user.get("username"),
            "avatar_url": (
                f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png"
                if avatar
                else None
            ),
        }

    raise ValueError(f"Unsupported provider: {provider}")