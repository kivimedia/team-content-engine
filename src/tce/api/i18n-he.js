/* Hebrew UI for a Hebrew workspace (5-Oct). Loaded ONLY when the page is served to
 * a login whose workspace language is "he" (see dashboard.py); the owner's pages
 * never reference this file, so they stay byte for byte as they were.
 *
 * It translates the interface, never the content: an exact English UI string, or
 * one of the patterns below, becomes Hebrew. Script text, titles and notes are
 * already Hebrew and match no key, so they pass through untouched. The pages
 * render a lot of their text at runtime, so a MutationObserver translates what
 * they write as they write it. */
(function (root) {
  "use strict";

  var EXACT = {
    // Navigation and frame
    "Today": "היום",
    "Topics": "נושאים",
    "This week": "השבוע",
    "Record": "הקלטה",
    "Library": "ספרייה",
    "Settings": "הגדרות",
    "Sections": "אזורים",
    "Back to KM BOT": "חזרה ל-KM BOT",
    "Back to Today": "חזרה להיום",
    "Talk with TCE": "לדבר עם TCE",
    "Loading": "טוען",
    "Opening your workspace": "פותח את סביבת העבודה שלך",
    "Editorial workspace": "סביבת העבודה שלך",
    "TCE Recording Studio": "אולפן ההקלטות",

    // Recording studio: queue and opening step
    "Walking studio": "אולפן הליכה",
    "Loading your scripts": "טוען את התסריטים שלך",
    "This recording sitting": "ההקלטה של עכשיו",
    "Ready to record": "מוכן להקלטה",
    "Tap one and the camera opens. Each idea keeps its own clips, so you can move between scripts without losing a take.":
      "בוחרים אחד והמצלמה נפתחת. לכל רעיון יש קליפים משלו, אז אפשר לעבור בין תסריטים בלי לאבד אף טייק.",
    "Nothing is ready to record yet": "עדיין אין משהו מוכן להקלטה",
    "Choose your topics in Topics and prepare their scripts from This week.":
      "בוחרים נושאים בלשונית נושאים ומכינים להם תסריט מתוך השבוע.",
    "Step 1 of 2": "שלב 1 מתוך 2",
    "Choose how it opens": "בוחרים איך זה נפתח",
    "The first spoken line. Everything after it stays the same.": "המשפט הראשון שאומרים. כל מה שאחריו נשאר אותו דבר.",
    "Ask for more openings": "עוד פתיחות",
    "Choose the opening": "בוחרים פתיחה",
    "Pick the first spoken line. The rest of the script stays the same.":
      "בוחרים את המשפט הראשון. שאר התסריט נשאר אותו דבר.",
    "Choose another opening, or fix the line in the script first.": "בוחרים פתיחה אחרת, או מתקנים קודם את המשפט בתסריט.",
    "Creating the packet version with this opening": "מכין גרסה עם הפתיחה הזאת",
    "Recommended": "מומלץ",
    "Use this opening": "להשתמש בפתיחה הזאת",
    "Open the script": "לפתוח את התסריט",
    "That script is not ready to record yet. Here is what is.": "התסריט הזה עוד לא מוכן להקלטה. הנה מה שכן מוכן.",
    "Could not load scripts": "לא הצלחתי לטעון את התסריטים",

    // Recording studio: camera and teleprompter
    "Front camera": "מצלמה קדמית",
    "Camera and microphone start only when you press Record.": "המצלמה והמיקרופון נדלקים רק כשלוחצים הקלטה.",
    "Recording": "מקליט",
    "Recording interrupted. Check the camera before continuing.": "ההקלטה נקטעה. כדאי לבדוק את המצלמה לפני שממשיכים.",
    "Points": "נקודות",
    "Full script": "תסריט מלא",
    "Reader mode": "מצב קריאה",
    "Jump to a point": "קפיצה לנקודה",
    "Next points": "הנקודות הבאות",
    "Earlier points": "הנקודות הקודמות",
    "Swap words and video": "להחליף בין הטקסט לווידאו",
    "Words over the video": "טקסט על הווידאו",
    "Text size": "גודל טקסט",
    "Bigger text": "טקסט גדול יותר",
    "Smaller text": "טקסט קטן יותר",
    "Darker background": "רקע כהה יותר",
    "Lighter background": "רקע בהיר יותר",
    "Opening": "פתיחה",
    "Change": "להחליף",
    "Recording controls": "כפתורי הקלטה",
    "Pause": "השהיה",
    "Resume": "המשך",
    "Stop": "עצור",
    "keep this take": "שומרים את הטייק",
    "Finish": "סיום",
    "send for editing": "שולחים לעריכה",
    "Paused. The current clip is still open.": "מושהה. הקליפ הנוכחי עדיין פתוח.",
    "Clip saved and checked for camera and microphone tracks.": "הקליפ נשמר, ויש בו תמונה וקול.",
    "Nothing recorded yet, so there is nothing to send for editing.": "עוד לא הוקלט כלום, אז אין מה לשלוח לעריכה.",
    "Assembling clips and checking audio": "מחבר את הקליפים ובודק את הקול",
    "Sending a clip that did not get through before": "שולח קליפ שלא עבר קודם",
    "Sending the end of the last clip before building the video": "שולח את סוף הקליפ האחרון לפני שבונים את הסרטון",
    "Session saved as one editable recording. Every source clip is retained.":
      "ההקלטה נשמרה כקובץ אחד לעריכה. כל הקליפים המקוריים נשמרו.",
    "Save this clip before switching?": "לשמור את הקליפ לפני שעוברים?",
    "The clip will stay with this script. The next script opens as soon as the bytes are safe on this phone.":
      "הקליפ יישאר עם התסריט הזה. התסריט הבא ייפתח ברגע שהקליפ שמור בטלפון.",
    "Stay here": "להישאר כאן",
    "Save clip and switch": "לשמור ולעבור",

    // Workspace: pages, headings, buttons
    "Start recording": "להתחיל להקליט",
    "Topic": "נושא",
    "No script yet": "עוד אין תסריט",
    "Script ready": "התסריט מוכן",
    "Post": "פוסט",
    "Opening the conversation": "פותח את השיחה",
    "Needs you": "מחכה לך",
    "Needs you.": "מחכה לך.",
    "Done.": "בוצע.",
    "Done": "בוצע",
    "Ask for a rewrite": "לבקש שכתוב",
    "Your request is done": "הבקשה שלך בוצעה",
    "Your notes on this video": "ההערות שלך על הסרטון",
    "Your angle": "הזווית שלך",
    "You": "אתה",
    "Written by you.": "נכתב על ידך.",
    "Working on your request": "עובד על הבקשה שלך",
    "Working on it.": "עובד על זה.",
    "Why this is yours": "למה זה שלך",
    "Why now": "למה עכשיו",
    "Who it helps": "למי זה עוזר",
    "When to post": "מתי לפרסם",
    "What to ask for": "מה לבקש",
    "What they should take away": "מה הם צריכים לקחת מזה",
    "Use the new version": "להשתמש בגרסה החדשה",
    "Undone.": "בוטל.",
    "Undo": "ביטול",
    "Type instead of talking": "להקליד במקום לדבר",
    "Title": "כותרת",
    "This week's list": "הרשימה של השבוע",
    "This idea": "הרעיון הזה",
    "The point": "הנקודה",
    "The engine is not available right now.": "המנוע לא זמין כרגע.",
    "Talk it through first": "קודם לדבר על זה",
    "Talk about this week": "לדבר על השבוע",
    "Talk about this topic": "לדבר על הנושא",
    "Talk about this script": "לדבר על התסריט",
    "Talk about this": "לדבר על זה",
    "Talk about the whole week": "לדבר על כל השבוע",
    "Sending": "שולח",
    "Send": "שליחה",
    "Script being written": "התסריט נכתב",
    "Script": "תסריט",
    "Scheduled": "מתוזמן",
    "Say something first.": "קודם להגיד משהו.",
    "Saving": "שומר",
    "Save": "שמירה",
    "Restore": "שחזור",
    "Restoring": "משחזר",
    "Record it this week": "להקליט השבוע",
    "Ready to post": "מוכן לפרסום",
    "Reading your week": "קורא את השבוע שלך",
    "Reading your settings": "קורא את ההגדרות שלך",
    "Reading your notes back": "קורא את ההערות שלך",
    "Reading what you have recorded": "קורא מה שהקלטת",
    "Reading this week's list": "קורא את הרשימה של השבוע",
    "Reading the ideas waiting for you": "קורא את הרעיונות שמחכים לך",
    "Put back": "להחזיר",
    "Proposed change": "שינוי מוצע",
    "Prepare the script": "להכין תסריט",
    "Posted": "פורסם",
    "Posting now": "מפרסם עכשיו",
    "Point": "נקודה",
    "Pick one, or say what you want changed.": "בוחרים אחד, או אומרים מה לשנות.",
    "Parts of the script": "חלקי התסריט",
    "Outline": "שלד",
    "Or say exactly what you want changed...": "או להגיד בדיוק מה לשנות...",
    "Opening the topic": "פותח את הנושא",
    "Opening the script": "פותח את התסריט",
    "Openings": "פתיחות",
    "One more": "עוד אחד",
    "One fewer": "אחד פחות",
    "Not this week, keep as a spare": "לא השבוע, לשמור ברזרבה",
    "Nothing said yet": "עוד לא נאמר כלום",
    "No ideas match this filter.": "אין רעיונות שמתאימים לסינון.",
    "Make it sound more like me": "שיישמע יותר כמוני",
    "Make it shorter": "לקצר",
    "Make it more practical": "יותר פרקטי",
    "Make it more opinionated": "יותר דעתני",
    "Make it less corporate": "פחות תאגידי",
    "Line": "שורה",
    "Jennifer's rules": "הכללים של ג'ניפר",
    "Jennifer has a question.": "לג'ניפר יש שאלה.",
    "In this week's list.": "ברשימה של השבוע.",
    "In the reserve list.": "ברשימת הרזרבה.",
    "Give notes on the new version": "הערות על הגרסה החדשה",
    "Filter topics": "סינון נושאים",
    "Filter recordings": "סינון הקלטות",
    "Everything you have recorded, and what happened to it.": "כל מה שהקלטת, ומה קרה איתו.",
    "Edit": "עריכה",
    "Download the edit": "להוריד את העריכה",
    "Download": "הורדה",
    "Did not go out": "לא יצא",
    "Description": "תיאור",
    "Could not load": "לא הצלחתי לטעון",
    "Choose when to post first.": "קודם בוחרים מתי לפרסם.",
    "Choose this week's topics": "לבחור את הנושאים של השבוע",
    "Caption": "כיתוב",
    "Being changed": "בשינוי",
    "All your ideas and this week": "כל הרעיונות שלך והשבוע",
    "Talk to Jennifer": "לדבר עם ג'ניפר",
    "Close the conversation": "לסגור את השיחה",
    "Close the notes. They stay saved.": "לסגור את ההערות. הן נשמרות.",
    "What this conversation may do": "מה השיחה הזאת יכולה לעשות",
    "Discuss": "לדבר",
    "Propose changes": "להציע שינויים",
    "Say what you think. Nothing changes unless you accept it.": "תגיד מה אתה חושב. שום דבר לא משתנה בלי שתאשר.",
    "Read replies out loud": "להקריא את התשובות",
    "Read aloud": "הקראה",
    "Replies will be read out loud.": "התשובות יוקראו בקול.",
    "Replies stay silent.": "התשובות לא יוקראו.",
    "Checking again every few seconds": "בודק שוב כל כמה שניות",
    "Your next useful action.": "הצעד הבא שלך.",
    "scripts ready": "תסריטים מוכנים",
    "need a decision": "מחכים להחלטה",
    "changes to review": "שינויים לבדיקה",
    "being edited": "בעריכה",
    "This week's recording list": "רשימת ההקלטות של השבוע",
    "Notifications are blocked in your browser settings.": "ההתראות חסומות בהגדרות הדפדפן.",
    "Type": "הקלדה",
    "is first.": "ראשון בתור.",
    "Other": "אחר"
  };

  var PATTERNS = [
    [/^Point (\d+)$/, "נקודה $1"],
    [/^Version (\d+)$/, "גרסה $1"],
    [/^Script version (\d+)$/, "תסריט, גרסה $1"],
    [/^Option (\d+)$/, "אפשרות $1"],
    [/^(\d+) ready scripts?$/, "$1 תסריטים מוכנים"],
    [/^(\d+) ideas? waiting$/, "$1 רעיונות מחכים"],
    [/^(\d+) other$/, "$1 אחר"],
    [/^([\s\S]+) is first\.$/, "$1 ראשון."],
    [/^Recommended(.*)$/, "מומלץ$1"],
    [/^Why \(private\): ([\s\S]*)$/, "למה (רק לך): $1"],
    [/^Viewer question: ([\s\S]*)$/, "השאלה של הצופה: $1"],
    [/^Recording did not start: ([\s\S]*)$/, "ההקלטה לא התחילה: $1"],
    [/^The camera did not come back: ([\s\S]*)$/, "המצלמה לא חזרה: $1"],
    [/^Lost contact while waiting: ([\s\S]*)$/, "הקשר נותק בזמן ההמתנה: $1"],
    [/^Opening changed\. Packet version (\d+) is bound to this take set\.$/, "הפתיחה הוחלפה. גרסה $1 מחוברת להקלטה הזאת."]
  ];

  function translate(text) {
    if (typeof text !== "string") return null;
    var key = text.trim();
    if (!key) return null;
    if (Object.prototype.hasOwnProperty.call(EXACT, key)) return text.replace(key, EXACT[key]);
    for (var i = 0; i < PATTERNS.length; i += 1) {
      if (PATTERNS[i][0].test(key)) return text.replace(key, key.replace(PATTERNS[i][0], PATTERNS[i][1]));
    }
    return null;
  }

  var ATTRS = ["aria-label", "title", "placeholder"];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1 };

  function translateNode(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      var parent = node.parentNode;
      if (parent && SKIP[parent.nodeName]) return;
      var out = translate(node.nodeValue);
      if (out !== null && out !== node.nodeValue) node.nodeValue = out;
      return;
    }
    if (node.nodeType !== 1 || node.nodeName === "SCRIPT" || node.nodeName === "STYLE") return;
    ATTRS.forEach(function (name) {
      if (!node.hasAttribute(name)) return;
      var val = node.getAttribute(name);
      var tr = translate(val);
      if (tr !== null && tr !== val) node.setAttribute(name, tr);
    });
    var child = node.firstChild;
    while (child) {
      translateNode(child);
      child = child.nextSibling;
    }
  }

  var api = { lang: "he", translate: translate, translateNode: translateNode, EXACT: EXACT };
  root.TCE_I18N = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;

  if (typeof document === "undefined" || typeof MutationObserver === "undefined") return;
  var observer = new MutationObserver(function (records) {
    records.forEach(function (r) {
      if (r.type === "characterData") translateNode(r.target);
      else if (r.type === "attributes") translateNode(r.target);
      else r.addedNodes.forEach(translateNode);
    });
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, characterData: true,
    attributes: true, attributeFilter: ATTRS
  });
  function all() {
    translateNode(document.documentElement);
    if (document.title) {
      var t = translate(document.title);
      if (t) document.title = t;
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", all);
  else all();
})(typeof window !== "undefined" ? window : globalThis);
