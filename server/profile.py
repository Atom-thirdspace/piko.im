def fetch_profile(provider, client , token):
    if provider == "google":
        info = token.get("userinfo") or client.userinfo(token=token)
        return{
            "provider" : "google",
            "provider_user_id" : info["sub"],
            "email" : info.get("email"),
            "name" : info.get("name") or info.get("email"),
            "avatar_url" : info.get("picture"),
            "email_verified": bool(info.get("email_verified")),
        }

    if provider == "github":
        user = client.get("user", token=token).json()
        email = user.get("email")
        primary = None
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
            # Only the /user/emails route tells us the address is verified.
            "email_verified": primary is not None,
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
            "email_verified": bool(user.get("verified")),
        }

    if provider == "hackclub":
        info = token.get("userinfo") or client.get("api/v1/me", token=token).json()
        return {
            "provider": "hackclub",
            "provider_user_id": str(info.get("sub") or info.get("id")),
            "email": info.get("email"),
            "name": info.get("name") or info.get("nickname") or info.get("email"),
            "avatar_url": info.get("picture"),      # not part of the documented claims
            "email_verified": bool(info.get("email_verified", True)),
        }

    raise ValueError(f"Unsupported provider: {provider}")