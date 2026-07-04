"""
Climate Action Tracker — merged edition.

This app is a deliberate merge of three independent implementations of
the same brief (built separately with ChatGPT, Claude, and Gemini).
Rather than pick one and throw the others away, the goal was to keep
whichever version of each piece was strongest:

  - Auth/session handling: the `g.user` + `login_required` decorator
    pattern (clean, idiomatic Flask, easy to extend).
  - User feedback: flash messages with categories and a couple of
    personalized touches (e.g. greeting the user by name on login).
  - Activity deletion: NO JavaScript confirm() dialogs. Instead there
    is a real server-rendered confirmation page — you still get a
    "are you sure?" step, it's just a second page instead of a popup.
  - Everything is rendered with Jinja2 templates and all
    password handling goes through Werkzeug's security helpers
    (generate_password_hash / check_password_hash).
"""
from datetime import date, datetime
from functools import wraps
import os

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

from models import (
    ACTIVITY_ICONS,
    ACTIVITY_POINTS,
    create_activity,
    create_user,
    delete_activity,
    get_activity_by_id,
    get_db_path,
    get_user_activities,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    get_user_statistics,
    init_db,
    update_activity,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "climate-action-tracker-secret-key")
app.config["DATABASE"] = get_db_path()

# The date picker should only ever offer sensible years — no 1800s,
# no 2100s. Enforced both in the HTML (min/max on the <input>) and
# here on the server, since the HTML attributes alone can't be trusted.
MIN_ACTIVITY_YEAR = 1900
MAX_ACTIVITY_YEAR = 2099
MIN_ACTIVITY_DATE = f"{MIN_ACTIVITY_YEAR}-01-01"
MAX_ACTIVITY_DATE = f"{MAX_ACTIVITY_YEAR}-12-31"

# Made available to every template automatically, so add/edit forms
# and the dashboard can all show the icon + point value without
# duplicating this dict anywhere.
app.jinja_env.globals["ACTIVITY_ICONS"] = ACTIVITY_ICONS
app.jinja_env.globals["MIN_ACTIVITY_DATE"] = MIN_ACTIVITY_DATE
app.jinja_env.globals["MAX_ACTIVITY_DATE"] = MAX_ACTIVITY_DATE


def parse_activity_date(date_str):
    """Parse a YYYY-MM-DD string and confirm the year is in range.

    Returns the date string unchanged if valid, or None if the date is
    malformed or outside the 1900–2099 window.
    """
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

    if not (MIN_ACTIVITY_YEAR <= parsed.year <= MAX_ACTIVITY_YEAR):
        return None

    return date_str


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view_function(*args, **kwargs)

    return wrapped_view


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password or not confirm_password:
            flash("All fields are required.", "error")
        elif len(username) < 3:
            flash("Username must be at least 3 characters long.", "error")
        elif "@" not in email or "." not in email.split("@")[-1]:
            flash("Please enter a valid email address.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif get_user_by_username(username) is not None:
            flash("That username is already taken.", "error")
        elif get_user_by_email(email) is not None:
            flash("An account with that email already exists.", "error")
        else:
            create_user(username, email, password)
            flash("Account created successfully. You can log in now.", "success")
            return redirect(url_for("login"))

        return render_template("register.html", username=username, email=email)

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_username(username)
        if user is None or not user.check_password(password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username)

        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
        flash(f"Welcome back, {user.username}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    activities = get_user_activities(g.user.id)
    total_points = sum(activity.points for activity in activities)
    return render_template(
        "dashboard.html",
        activities=activities,
        total_points=total_points,
        total_activities=len(activities),
    )


@app.route("/activity/add", methods=["GET", "POST"])
@login_required
def add_activity():
    if request.method == "POST":
        activity_type = request.form.get("activity_type", "")
        activity_date = request.form.get("activity_date", str(date.today()))
        notes = request.form.get("notes", "").strip()

        valid_date = parse_activity_date(activity_date)

        if activity_type not in ACTIVITY_POINTS:
            flash("Please select a valid activity.", "error")
            return render_template(
                "add_activity.html",
                activity_points=ACTIVITY_POINTS,
                today=str(date.today()),
                notes=notes,
            )

        if valid_date is None:
            flash(f"Please enter a valid date between {MIN_ACTIVITY_YEAR} and {MAX_ACTIVITY_YEAR}.", "error")
            return render_template(
                "add_activity.html",
                activity_points=ACTIVITY_POINTS,
                today=str(date.today()),
                notes=notes,
            )

        points = ACTIVITY_POINTS[activity_type]
        create_activity(g.user.id, activity_type, points, valid_date, notes)
        flash("Activity logged successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_activity.html", activity_points=ACTIVITY_POINTS, today=str(date.today()))


@app.route("/activity/edit/<int:activity_id>", methods=["GET", "POST"])
@login_required
def edit_activity(activity_id):
    activity = get_activity_by_id(activity_id)

    if activity is None or activity.user_id != g.user.id:
        flash("Activity not found.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        activity_type = request.form.get("activity_type", "")
        activity_date = request.form.get("activity_date", activity.activity_date)
        notes = request.form.get("notes", "").strip()

        valid_date = parse_activity_date(activity_date)

        if activity_type not in ACTIVITY_POINTS:
            flash("Please select a valid activity.", "error")
            return render_template("edit_activity.html", activity=activity, activity_points=ACTIVITY_POINTS)

        if valid_date is None:
            flash(f"Please enter a valid date between {MIN_ACTIVITY_YEAR} and {MAX_ACTIVITY_YEAR}.", "error")
            return render_template("edit_activity.html", activity=activity, activity_points=ACTIVITY_POINTS)

        points = ACTIVITY_POINTS[activity_type]
        update_activity(activity_id, activity_type, points, valid_date, notes)
        flash("Activity updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_activity.html", activity=activity, activity_points=ACTIVITY_POINTS)


@app.route("/activity/delete/<int:activity_id>")
@login_required
def confirm_delete_activity(activity_id):
    """Show a real confirmation page instead of a JavaScript confirm()."""
    activity = get_activity_by_id(activity_id)

    if activity is None or activity.user_id != g.user.id:
        flash("Activity not found.", "error")
        return redirect(url_for("dashboard"))

    return render_template("confirm_delete.html", activity=activity)


@app.route("/activity/delete/<int:activity_id>", methods=["POST"])
@login_required
def delete_activity_route(activity_id):
    activity = get_activity_by_id(activity_id)

    if activity is None or activity.user_id != g.user.id:
        flash("Activity not found.", "error")
    else:
        delete_activity(activity_id)
        flash("Activity deleted successfully.", "success")

    return redirect(url_for("dashboard"))


@app.route("/statistics")
@login_required
def statistics():
    stats = get_user_statistics(g.user.id)

    if stats["total_activities"] == 0:
        progress_summary = "Start by adding your first climate-positive action."
    elif stats["total_points"] >= 50:
        progress_summary = "Excellent progress. Your actions are building a strong positive impact."
    elif stats["total_points"] >= 20:
        progress_summary = "You are making solid progress with consistent sustainable choices."
    else:
        progress_summary = "Great start. Keep logging activities to grow your impact."

    return render_template(
        "statistics.html",
        total_activities=stats["total_activities"],
        total_points=stats["total_points"],
        most_common_activity=stats["most_common_activity"],
        average_points=stats["average_points"],
        breakdown=stats["breakdown"],
        progress_summary=progress_summary,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
