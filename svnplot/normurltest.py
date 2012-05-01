import re
URL_NORM_RE = re.compile('[/]+')

def normurlpath(pathstr):
    '''
    normalize url path. I cannot use 'normpath' directory as it changes path seperator to 'os' default path seperator.
    '''
    nrmpath = pathstr
    if( nrmpath):
        nrmpath = re.sub(URL_NORM_RE, '/', nrmpath)
        #nrmpath = makeunicode(nrmpath)        
        assert(pathstr[-1] == nrmpath[-1])
        
    return(nrmpath)
    
def test():
    print 'running tests'
    assert('/test/' == normurlpath('//test//'))
    assert('/test' == normurlpath('//test'))
    assert('test' == normurlpath('test'))
    assert('/test' == normurlpath('/test'))
    assert('/test/' == normurlpath('/test/'))
    assert('/test/' == normurlpath('////test/'))
    assert('/test/test/' == normurlpath('////test/test//'))
    
test()