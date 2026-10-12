"""Produce real backend control ACK for a Java-emitted ROLE, with no business calls."""
import json
from pathlib import Path
import sys
from run import MobileAgentStateMachine, UIListener

def main():
    role=json.loads(Path(sys.argv[1]).read_text())
    calls=[];sent=[]
    def forbidden(*args,**kwargs):calls.append(1);raise AssertionError('business work during handshake')
    agent=MobileAgentStateMachine(chat=forbidden,tts=forbidden,voice=forbidden,beep=forbidden)
    listener=UIListener(agent,send=sent.append)
    listener._process_message(json.dumps(role))
    assert calls==[] and len(sent)==1
    expected=dict(type='SESSION_READY',protocolVersion=1,context=role['context'],requestId=role['requestId'])
    assert json.loads(sent[0])==expected
    Path(sys.argv[2]).write_text(sent[0])
    print('cross_language_session_ready=PASS model_calls=0')
if __name__=='__main__':main()
