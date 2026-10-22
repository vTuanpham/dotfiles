# Bash reads this before .profile; keep login setup in one place.
[ ! -r "$HOME/.profile" ] || . "$HOME/.profile"
