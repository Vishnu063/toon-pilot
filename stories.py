"""Small original offline story templates; finite variation, not an AI author."""
import datetime


def for_day(day=None, language='en'):
    day = datetime.date.today() if day is None else datetime.date.fromisoformat(str(day))
    if language not in ('en', 'hi'):
        raise ValueError('Choose English or Hindi.')
    index = day.toordinal() % 3
    english = [
        ('Sharing a sunny day', 'Milo finds a yellow flower in the garden. Pip brings a little blue ribbon. They share their treasures, dance together, and wave goodbye.'),
        ('A little helping hand', 'Pip drops a basket beside the garden path. Milo helps gather the little flowers. Pip smiles and says thank you. Helping friends makes a happy day.'),
        ('Taking turns', 'Milo and Pip invent a hopping game. First Milo hops while Pip claps. Then Pip hops while Milo claps. Taking turns means both friends can play.'),
    ]
    hindi = [
        ('धूप वाला दिन', 'मिलो बगीचे में एक फूल देखता है। पिप एक नीला रिबन लाती है। दोनों अपनी चीजें बाँटते हैं। फिर वे साथ खेलते हैं।'),
        ('दोस्त की मदद', 'पिप के फूल रास्ते में गिर जाते हैं। मिलो फूल उठाने में उसकी मदद करता है। पिप धन्यवाद कहती है। दोनों खुश हैं।'),
        ('बारी बारी खेलें', 'मिलो और पिप कूदने का खेल खेलते हैं। पहले मिलो कूदता है। फिर पिप कूदती है। दोनों बारी बारी खेलकर खुश होते हैं।'),
    ]
    title, text = (english if language == 'en' else hindi)[index]
    return dict(title=title, text=text, duration=30, language=language,
                characters=['milo','pip'], voice=language+'-boy', orientation='portrait',mode='lite')
