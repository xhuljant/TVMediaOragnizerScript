import os
import re
import shutil
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# -- CONFIG --
load_dotenv()  # reads the .env file in the current directory

SOURCE_DIR = os.getenv("SOURCE_DIR")
DEST_DIR = os.getenv("DEST_DIR")
LOG_DIR = os.getenv("LOG_DIR", os.path.dirname(__file__))
LOG_FILE = os.path.join(LOG_DIR, "tv_show_organizer.log")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))  # Adjust based on drive speeds (keep low for HDDs, can raise to 8+ for NVMe/SSDs)

# When True, a trailing "(YYYY)" is stripped from the derived show name so that,
# e.g., an "Impractical Jokers (2011)" season pack and loose "Impractical Jokers"
# S12 files collapse into ONE library folder instead of two. Set False if you
# prefer Plex-style "Show Name (Year)" folders.
STRIP_YEAR_FROM_SHOW = os.getenv("STRIP_YEAR_FROM_SHOW", "True").lower() in ("true", "1", "yes")

# --- LOGGING ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",  # avoid the mojibake ("\ufffd") seen in the old log
)

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}

# Folder names that are just structural containers, never a show title.
STRUCTURAL_FOLDER_NAMES = {"series", "season", "seasons", "extras", "specials", "tv show", "tv shows"}

# Quality / release cruft to trim off the tail of an episode title.
QUALITY_CRUFT = re.compile(
    r"\b("
    r"1080[pi]|720[pi]|480[pi]|2160[pi]|4k|60fps|10bit|8bit|"
    r"web[\s._-]?dl|web[\s._-]?rip|webrip|web|bluray|blu[\s._-]?ray|brrip|"
    r"hdtv|dvdrip|hdrip|remux|"
    r"x264|x265|h[\s._-]?264|h[\s._-]?265|hevc|avc|xvid|divx|"
    r"aac|ac3|mp3|dts(?:[\s._-]?hd)?|dd[\s._-]?p?[\s._-]?5[\s._.]?1|ddp?5[\s._.]?1|opus|flac|atmos|truehd|"
    r"amzn|nf|dsnp|hmax|atvp|hulu|"
    r"repack|proper|internal|extended|uncut"
    r").*$",
    flags=re.IGNORECASE,
)

# Leading/trailing separators & bracket junk left behind after stripping cruft.
EDGE_JUNK = re.compile(r"^[\s._\-\[\](){}+]+|[\s._\-\[\](){}+]+$")


def smart_title(text):
    """Title-case the first letter of each word without breaking apostrophes
    or interior letters ("Hoe's" not "Hoe'S", "OK" stays sane)."""
    return re.sub(r"[A-Za-z]+('[A-Za-z]+)?",
                  lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(),
                  text)


def clean_episode_title(title):
    if not title:
        return ""
    title = re.sub(r"[._]", " ", title)
    title = QUALITY_CRUFT.sub("", title)
    # Remove any leftover bracketed blocks e.g. "[EZTVx.to]".
    title = re.sub(r"[\[(][^\])]*[\])]", "", title)
    title = re.sub(r"\s{2,}", " ", title)
    title = EDGE_JUNK.sub("", title)
    return smart_title(title.strip())


def strip_site_prefix(name):
    name = re.sub(r'^[\w\s]+[\s.](org|com|net|mx|to|gg|xyz|info)\s*[-\u2013]\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^www\s+[\w\s]+\s*[-\u2013]\s*', '', name, flags=re.IGNORECASE)
    return name


# --- HELPER: Extract Show Name, Season, Episode, and Title ---
# NOTE: the show-name group is now OPTIONAL. Files like "S07E16.mkv" (no show
# name in the filename) now parse successfully; the caller supplies the show
# name from the parent folder.
_PAT_SxxExx = re.compile(
    r"(?:(?P<show>.+?)[\s._-]+)?[Ss](?P<s>\d{1,2})[Ee](?P<e>\d{1,2})(?:[\s._-]+(?P<title>.+))?$"
)
# "1x02" style. Guarded so it won't fire on resolutions like 1920x1080.
_PAT_NxNN = re.compile(
    r"(?:(?P<show>.+?)[\s._-]+)?(?<!\d)(?P<s>\d{1,2})x(?P<e>\d{1,2})(?!\d)(?:[\s._-]+(?P<title>.+))?$"
)


def extract_episode_info(name):
    """Extract show name, season, episode number, and episode title from filename."""
    name = strip_site_prefix(name)

    match = _PAT_SxxExx.search(name) or _PAT_NxNN.search(name)
    if not match:
        return None

    show_name = match.group("show") or ""
    season = match.group("s").zfill(2)
    episode = match.group("e").zfill(2)
    episode_title = match.group("title") or ""

    # Clean up show name (may be empty -> caller fills from folder)
    show_name = re.sub(r"[._]", " ", show_name).strip()
    show_name = re.sub(r"\s{2,}", " ", show_name)
    show_name = smart_title(show_name)

    return {
        "show": show_name,          # may be "" — resolved by caller
        "season": season,
        "episode": episode,
        "title": clean_episode_title(episode_title),
    }


# --- HELPER: Clean Folder Name ---
def clean_show_name(folder_name):
    """Extract a clean show name from a folder that might have random characters."""
    folder_name = strip_site_prefix(folder_name)

    info = extract_episode_info(folder_name)
    if info and info["show"]:
        clean = info["show"]
    else:
        clean = re.sub(
            r"\b(Season|Series|Complete|S\d+([\s._-]*S\d+)?|1080p|720p|WEB-?DL|BluRay).*$",
            "", folder_name, flags=re.IGNORECASE,
        )
        clean = re.sub(r"[._]", " ", clean).strip()
        clean = re.sub(r"\s{2,}", " ", clean)
        clean = smart_title(clean)

    clean = clean.strip()
    if STRIP_YEAR_FROM_SHOW:
        clean = re.sub(r"\s*\(\d{4}\)\s*$", "", clean).strip()

    return clean if clean else strip_site_prefix(folder_name).strip()


def resolve_show_name_from_path(file_path, top_level_path):
    """
    Walk from the file up to (but not past) the top-level source item, returning
    the first ancestor folder name that looks like a real show title rather than
    a structural container ("Season 7", "Series", "Extras", ...).
    """
    current = os.path.dirname(file_path)
    top_parent = os.path.dirname(top_level_path)
    candidates = []
    while current and current != top_parent:
        base = os.path.basename(current)
        candidates.append(base)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    for base in candidates:
        stripped = re.sub(r"\bseason\b\s*\d*", "", base, flags=re.IGNORECASE).strip()
        if base.lower() in STRUCTURAL_FOLDER_NAMES or not stripped:
            continue
        name = clean_show_name(base)
        if name:
            return name

    # Fallback: the top-level item name itself.
    return clean_show_name(os.path.basename(top_level_path))


# --- MAIN PERFORMANCE WRAPPER FOR SINGLE WORKER TASKS ---
def process_single_tv_item(path):
    """Processes a single root item completely to prevent parallel track tangles."""
    item_name = os.path.basename(path)

    # 1. Identify files to process upfront
    files_to_process = []
    is_dir = os.path.isdir(path)

    if os.path.isfile(path):
        if os.path.splitext(item_name)[1].lower() in VIDEO_EXTENSIONS:
            files_to_process.append(path)
    elif is_dir:
        for root, _, files in os.walk(path):
            for file in files:
                if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                    files_to_process.append(os.path.join(root, file))

    if not files_to_process:
        return item_name, "skipped"

    files_moved = 0
    files_failed = 0  # video files we couldn't parse — these must NOT be deleted

    # 2. Sequential file moves for this specific show thread
    for file_path in files_to_process:
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)

        info = extract_episode_info(name)
        if not info:
            logging.warning(f"Could not parse episode info - leaving in place: {file_path}")
            files_failed += 1
            continue

        # Resolve show name: prefer the name embedded in the filename; otherwise
        # derive it from the nearest meaningful ancestor folder.
        if not info["show"]:
            if is_dir:
                info["show"] = resolve_show_name_from_path(file_path, path)
            else:
                info["show"] = clean_show_name(name)

        if not info["show"]:
            logging.warning(f"Parsed episode but no show name could be determined - leaving in place: {file_path}")
            files_failed += 1
            continue

        season_folder = os.path.join(DEST_DIR, info["show"], f"Season {info['season']}")
        os.makedirs(season_folder, exist_ok=True)

        if info["title"]:
            new_filename = f"{info['show']} - S{info['season']}E{info['episode']} - {info['title']}{ext}"
        else:
            new_filename = f"{info['show']} - S{info['season']}E{info['episode']}{ext}"

        dest_file = os.path.join(season_folder, new_filename)

        try:
            if not os.path.exists(dest_file):
                shutil.move(file_path, dest_file)
                logging.info(f"Moved episode: {filename} -> {dest_file}")
                files_moved += 1
            else:
                logging.warning(f"Skipped duplicate: {dest_file}")
                # Optional: Delete duplicate file from source to keep things clean
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        except Exception as e:
            # Treat a move failure as unhandled so we don't delete the source
            logging.error(f"Error handling file {filename}: {e}")
            files_failed += 1

    # 3. Clean up the source ONLY if every video file was handled.
    if files_failed > 0:
        logging.warning(
            f"Left in source ({files_failed} unparseable/unmoved file(s), "
            f"{files_moved} moved): {item_name}"
        )
        return item_name, "unparsed"

    if is_dir:
        try:
            shutil.rmtree(path)
            logging.info(f"Cleaned up source directory: {item_name}")
        except Exception as e:
            logging.warning(f"Could not remove root directory {item_name}: {e}")
    elif os.path.isfile(path):
        try:
            os.remove(path)
        except Exception as e:
            logging.warning(f"Could not remove source file {item_name}: {e}")

    return item_name, "processed" if files_moved > 0 else "skipped"


# --- MAIN PERFORMANCE ENGINE ---
def process_tv_shows():
    logging.info("Starting accelerated TV show organization...")
    print("Starting TV show organization...")

    if not os.path.exists(SOURCE_DIR):
        logging.error(f"Source directory not found: {SOURCE_DIR}")
        return

    items = [os.path.join(SOURCE_DIR, i) for i in os.listdir(SOURCE_DIR)]
    if not items:
        print("No items found inside the source directory.")
        return

    total = len(items)
    print(f"Found {total} target item(s). Deploying {MAX_WORKERS} async threads.\n")

    processed = skipped = unparsed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_tv_item, item): item for item in items}

        for idx, future in enumerate(as_completed(futures), 1):
            try:
                name, status = future.result()
                if status == "processed":
                    processed += 1
                elif status == "unparsed":
                    unparsed += 1
                else:
                    skipped += 1

                sys.stdout.write(f"\rProgress: {idx}/{total} ({int(idx/total*100)}%) | Active: {name[:30]}")
                sys.stdout.flush()
            except Exception as e:
                logging.error(f"Worker thread error: {e}")

    print(
        f"\n\nTV show processing complete! "
        f"Folders Cleaned: {processed} | "
        f"Skipped/Unchanged: {skipped} | "
        f"Left in source (couldn't parse): {unparsed}"
    )


if __name__ == "__main__":
    process_tv_shows()
    os._exit(0)