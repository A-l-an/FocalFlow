"""Manual TTS probe. Default execution is inert; --live uses network and audio."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true',
                        help='Send a synthetic phrase to the configured TTS provider and play audio')
    args = parser.parse_args(argv)
    if not args.live:
        print('No provider or audio calls made. Use --live to opt in to the manual TTS probe.')
        return
    from MobileAgent.api import text2audio
    text2audio('Synthetic FocalFlow audio check.')


if __name__ == '__main__':
    main()
