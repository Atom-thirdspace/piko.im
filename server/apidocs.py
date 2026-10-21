from flask import Blueprint, render_template, Response, request

from .models import API_SCOPES
from .publicapi import (DEFAULT_PER_PAGE, MAX_PER_PAGE, RATE_WINDOW, TIER_ANON,
                        TIER_KEY, TIER_PRO, VERSION)

docs_bp = Blueprint("apidocs", __name__)


@docs_bp.route("/developers/")
def index():
    return render_template(
        "developers.html",
        version=VERSION,
        scopes=API_SCOPES,
        window=RATE_WINDOW,
        tiers=[("No key", TIER_ANON, "Catalog endpoints only."),
               ("With a key", TIER_KEY, "Adds everything under /me."),
               ("With Piko Pro", TIER_PRO, "Same endpoints, higher ceiling.")],
        default_per_page=DEFAULT_PER_PAGE,
        max_per_page=MAX_PER_PAGE,
    )


@docs_bp.route("/robots.txt")
def robots():
    base = request.url_root.rstrip("/")
    body = "\n".join([
        "User-agent: *",
        "Allow: /$",
        "Allow: /problems",
        "Allow: /blog",
        "Allow: /u/",
        "Disallow: /admin",
        "Disallow: /settings",
        "Disallow: /api/",
        "Disallow: /oauth/",
        "Disallow: /submissions",
        "Sitemap: %s/sitemap.xml" % base,
        "",
    ])
    return Response(body, mimetype="text/plain")


@docs_bp.route("/sitemap.xml")
def sitemap():
    from .models import PUBLISHED, Post, Problem, Track, User, db

    base = request.url_root.rstrip("/")
    urls = [(base + "/", "daily"),
            (base + "/problems/", "daily"),
            (base + "/blog/", "weekly")]

    # Post uses its own "published" string, not the content PUBLISHED flag.
    for slug in db.session.execute(
            db.select(Post.slug).where(Post.status == "published")
            .order_by(Post.published_at.desc())).scalars():
        urls.append(("%s/blog/%s/" % (base, slug), "monthly"))

    for slug in db.session.execute(
            db.select(Problem.slug).where(Problem.status == PUBLISHED)
            .order_by(Problem.slug)).scalars():
        urls.append(("%s/problems/%s/" % (base, slug), "weekly"))

    for slug in db.session.execute(
            db.select(Track.slug).where(Track.status == PUBLISHED)).scalars():
        urls.append(("%s/learn/%s/" % (base, slug), "weekly"))

    for name in db.session.execute(
            db.select(User.username)
            .where(User.username.isnot(None),
                   # Honour the privacy setting: someone who opted out of
                   # being discoverable has not agreed to be indexed.
                   User.discoverable.is_(True),
                   User.is_suspended.is_(False))
            .limit(2000)).scalars():
        urls.append(("%s/u/%s/" % (base, name), "weekly"))

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq in urls:
        out.append("  <url><loc>%s</loc><changefreq>%s</changefreq></url>"
                   % (loc, freq))
    out.append("</urlset>")
    return Response("\n".join(out), mimetype="application/xml")
