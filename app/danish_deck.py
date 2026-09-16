"""Jeu de cartes français → danois fourni avec l'app (FlashCard.user_id nul).

Vocabulaire courant, choisi pour être utile tout de suite : politesse, verbes
de base, nombres, temps, salle de sport, quotidien, phrases pratiques.

Honnêteté sur la source : ces traductions sont écrites de mémoire, pas tirées
d'un dictionnaire officiel. Les formes données sont les formes de base
(infinitif « at ... » pour les verbes, forme définie pour les parties du
corps). Si l'une d'elles te semble fausse, supprime la carte ou corrige-la
depuis l'app — tes propres cartes priment.
"""
from sqlalchemy.orm import Session

from . import models

# (français, danois, indice, catégorie)
DECK: list[tuple[str, str, str | None, str]] = [
    # --- politesse et premiers échanges
    ("bonjour (la journée)", "goddag", None, "politesse"),
    ("salut", "hej", None, "politesse"),
    ("au revoir", "farvel", None, "politesse"),
    ("bonsoir", "godaften", None, "politesse"),
    ("bonne nuit", "godnat", None, "politesse"),
    ("merci", "tak", None, "politesse"),
    ("merci beaucoup", "mange tak", None, "politesse"),
    ("de rien", "selv tak", None, "politesse"),
    ("oui", "ja", None, "politesse"),
    ("non", "nej", None, "politesse"),
    ("peut-être", "måske", None, "politesse"),
    ("pardon / excuse-moi", "undskyld", None, "politesse"),
    ("à bientôt", "vi ses", None, "politesse"),
    ("bienvenue", "velkommen", None, "politesse"),
    ("comment ça va ?", "hvordan går det?", None, "politesse"),
    ("ça va bien", "det går godt", None, "politesse"),
    ("je m'appelle...", "jeg hedder...", None, "politesse"),
    ("parles-tu anglais ?", "taler du engelsk?", None, "politesse"),
    ("je ne comprends pas", "jeg forstår ikke", None, "politesse"),
    ("je ne parle pas danois", "jeg taler ikke dansk", None, "politesse"),
    ("peux-tu répéter ?", "kan du gentage det?", None, "politesse"),
    ("lentement", "langsomt", None, "politesse"),
    ("santé ! (trinquer)", "skål", None, "politesse"),
    ("bonne chance", "held og lykke", None, "politesse"),

    # --- pronoms et mots outils
    ("je", "jeg", None, "base"),
    ("tu", "du", None, "base"),
    ("il", "han", None, "base"),
    ("elle", "hun", None, "base"),
    ("nous", "vi", None, "base"),
    ("ils / elles", "de", None, "base"),
    ("et", "og", None, "base"),
    ("mais", "men", None, "base"),
    ("avec", "med", None, "base"),
    ("sans", "uden", None, "base"),
    ("pour", "for", None, "base"),
    ("parce que", "fordi", None, "base"),
    ("très", "meget", None, "base"),
    ("un peu", "lidt", None, "base"),
    ("beaucoup", "mange", "pour un nombre d'objets", "base"),
    ("aussi", "også", None, "base"),
    ("ici", "her", None, "base"),
    ("là-bas", "der", None, "base"),
    ("qui ?", "hvem?", None, "base"),
    ("quoi ?", "hvad?", None, "base"),
    ("où ?", "hvor?", None, "base"),
    ("quand ?", "hvornår?", None, "base"),
    ("pourquoi ?", "hvorfor?", None, "base"),
    ("comment ?", "hvordan?", None, "base"),

    # --- verbes courants
    ("être", "at være", None, "verbes"),
    ("avoir", "at have", None, "verbes"),
    ("faire", "at lave", None, "verbes"),
    ("aller", "at gå", "à pied", "verbes"),
    ("venir", "at komme", None, "verbes"),
    ("vouloir", "at ville", None, "verbes"),
    ("pouvoir", "at kunne", None, "verbes"),
    ("devoir", "at skulle", None, "verbes"),
    ("savoir", "at vide", None, "verbes"),
    ("manger", "at spise", None, "verbes"),
    ("boire", "at drikke", None, "verbes"),
    ("dormir", "at sove", None, "verbes"),
    ("travailler", "at arbejde", None, "verbes"),
    ("parler", "at tale", None, "verbes"),
    ("lire", "at læse", None, "verbes"),
    ("écrire", "at skrive", None, "verbes"),
    ("courir", "at løbe", None, "verbes"),
    ("nager", "at svømme", None, "verbes"),
    ("s'entraîner", "at træne", None, "verbes"),
    ("acheter", "at købe", None, "verbes"),
    ("payer", "at betale", None, "verbes"),
    ("comprendre", "at forstå", None, "verbes"),
    ("apprendre", "at lære", None, "verbes"),
    ("aider", "at hjælpe", None, "verbes"),
    ("attendre", "at vente", None, "verbes"),

    # --- nombres
    ("un", "en", None, "nombres"),
    ("deux", "to", None, "nombres"),
    ("trois", "tre", None, "nombres"),
    ("quatre", "fire", None, "nombres"),
    ("cinq", "fem", None, "nombres"),
    ("six", "seks", None, "nombres"),
    ("sept", "syv", None, "nombres"),
    ("huit", "otte", None, "nombres"),
    ("neuf", "ni", None, "nombres"),
    ("dix", "ti", None, "nombres"),
    ("vingt", "tyve", None, "nombres"),
    ("trente", "tredive", None, "nombres"),
    ("cent", "hundrede", None, "nombres"),
    ("mille", "tusind", None, "nombres"),

    # --- temps
    ("aujourd'hui", "i dag", None, "temps"),
    ("demain", "i morgen", None, "temps"),
    ("hier", "i går", None, "temps"),
    ("maintenant", "nu", None, "temps"),
    ("toujours", "altid", None, "temps"),
    ("jamais", "aldrig", None, "temps"),
    ("souvent", "ofte", None, "temps"),
    ("le matin", "morgen", None, "temps"),
    ("l'après-midi", "eftermiddag", None, "temps"),
    ("le soir", "aften", None, "temps"),
    ("la nuit", "nat", None, "temps"),
    ("la semaine", "uge", None, "temps"),
    ("le mois", "måned", None, "temps"),
    ("l'année", "år", None, "temps"),
    ("l'heure", "time", "durée d'une heure", "temps"),
    ("la minute", "minut", None, "temps"),
    ("lundi", "mandag", None, "temps"),
    ("mardi", "tirsdag", None, "temps"),
    ("mercredi", "onsdag", None, "temps"),
    ("jeudi", "torsdag", None, "temps"),
    ("vendredi", "fredag", None, "temps"),
    ("samedi", "lørdag", None, "temps"),
    ("dimanche", "søndag", None, "temps"),

    # --- sport et corps
    ("le corps", "kroppen", None, "sport"),
    ("le dos", "ryggen", None, "sport"),
    ("la jambe", "benet", None, "sport"),
    ("le bras", "armen", None, "sport"),
    ("l'épaule", "skulderen", None, "sport"),
    ("la poitrine", "brystet", None, "sport"),
    ("le ventre", "maven", None, "sport"),
    ("le cœur", "hjertet", None, "sport"),
    ("la main", "hånden", None, "sport"),
    ("le pied", "foden", None, "sport"),
    ("la tête", "hovedet", None, "sport"),
    ("le muscle", "musklen", None, "sport"),
    ("le poids", "vægt", None, "sport"),
    ("l'haltère", "håndvægt", None, "sport"),
    ("la salle de sport", "fitnesscenter", None, "sport"),
    ("l'entraînement", "træning", None, "sport"),
    ("la série", "sæt", None, "sport"),
    ("la répétition", "gentagelse", None, "sport"),
    ("le repos", "hvile", None, "sport"),
    ("l'échauffement", "opvarmning", None, "sport"),
    ("les étirements", "udstrækning", None, "sport"),
    ("transpirer", "at svede", None, "sport"),
    ("fatigué", "træt", None, "sport"),
    ("fort", "stærk", None, "sport"),
    ("la course à pied", "løb", None, "sport"),
    ("la natation", "svømning", None, "sport"),
    ("la piscine", "svømmehal", None, "sport"),
    ("le vélo", "cykel", None, "sport"),

    # --- quotidien
    ("l'eau", "vand", None, "quotidien"),
    ("le pain", "brød", None, "quotidien"),
    ("le lait", "mælk", None, "quotidien"),
    ("le café", "kaffe", None, "quotidien"),
    ("le thé", "te", None, "quotidien"),
    ("la bière", "øl", None, "quotidien"),
    ("le vin", "vin", None, "quotidien"),
    ("la pomme", "æble", None, "quotidien"),
    ("la viande", "kød", None, "quotidien"),
    ("le poisson", "fisk", None, "quotidien"),
    ("le légume", "grøntsag", None, "quotidien"),
    ("le fruit", "frugt", None, "quotidien"),
    ("le petit-déjeuner", "morgenmad", None, "quotidien"),
    ("le déjeuner", "frokost", None, "quotidien"),
    ("le dîner", "aftensmad", None, "quotidien"),
    ("la maison", "hus", None, "quotidien"),
    ("l'appartement", "lejlighed", None, "quotidien"),
    ("le travail", "arbejde", None, "quotidien"),
    ("l'argent", "penge", None, "quotidien"),
    ("le magasin", "butik", None, "quotidien"),
    ("la rue", "gade", None, "quotidien"),
    ("la ville", "by", None, "quotidien"),
    ("la voiture", "bil", None, "quotidien"),
    ("le train", "tog", None, "quotidien"),
    ("le temps qu'il fait", "vejr", None, "quotidien"),
    ("la pluie", "regn", None, "quotidien"),
    ("le soleil", "sol", None, "quotidien"),
    ("la neige", "sne", None, "quotidien"),
    ("froid", "kold", None, "quotidien"),
    ("chaud", "varm", None, "quotidien"),
    ("l'ami", "ven", None, "quotidien"),
    ("la famille", "familie", None, "quotidien"),

    # --- phrases pratiques
    ("combien ça coûte ?", "hvad koster det?", None, "phrases"),
    ("où est... ?", "hvor er...?", None, "phrases"),
    ("je voudrais...", "jeg vil gerne have...", None, "phrases"),
    ("l'addition, s'il vous plaît", "regningen, tak", None, "phrases"),
    ("aide-moi", "hjælp mig", None, "phrases"),
    ("j'ai faim", "jeg er sulten", None, "phrases"),
    ("j'ai soif", "jeg er tørstig", None, "phrases"),
    ("je suis fatigué", "jeg er træt", None, "phrases"),
    ("c'est bon", "det er godt", None, "phrases"),
    ("ça suffit", "det er nok", None, "phrases"),
    ("encore une fois", "en gang til", None, "phrases"),
    ("je ne sais pas", "det ved jeg ikke", None, "phrases"),
]


def seed_builtin_deck(db: Session) -> int:
    """Ajoute les cartes fournies avec l'app qui manquent encore. Idempotent :
    rien n'est écrasé, les cartes supprimées par un utilisateur ne reviennent
    pas puisqu'elles sont partagées (seules ses propres cartes lui appartiennent)."""
    existantes = {
        (c.front, c.back)
        for c in db.query(models.FlashCard).filter(models.FlashCard.user_id.is_(None)).all()
    }
    ajoutees = 0
    for front, back, hint, categorie in DECK:
        if (front, back) in existantes:
            continue
        db.add(models.FlashCard(
            user_id=None, language="da", front=front, back=back,
            hint=hint, category=categorie, source="integre",
        ))
        ajoutees += 1
    if ajoutees:
        db.commit()
    return ajoutees
