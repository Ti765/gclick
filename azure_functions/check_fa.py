import sys, pathlib, traceback
sys.path.insert(0, str(pathlib.Path('.').resolve()))
try:
    import function_app as fa
    print('Imported function_app')
    print('FEATURES[teams_bot]=', fa.FEATURES['teams_bot'])
    print('APP_ID present=', bool(fa.APP_ID))
    print('APP_PASSWORD present=', bool(fa.APP_PASSWORD))
    print('import_style=', getattr(fa, 'import_style', None))
    print('bot_sender is None? ', fa.bot_sender is None)
    print('conversation_storage is None? ', fa.conversation_storage is None)
except Exception:
    traceback.print_exc()
