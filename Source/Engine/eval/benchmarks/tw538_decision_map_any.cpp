// decision map with auto LSTM/TF weights
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "NeuralTFPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"
using Formosa::Gramambular2::ReadingGrid;
using iBopomofo::CorpusBigramContextModel;
using iBopomofo::NeuralLMPathScorer;
using iBopomofo::NeuralTFPathScorer;
using iBopomofo::ParselessLM;
namespace {
std::vector<std::string> splitSyllables(const std::string& readings) {
  std::vector<std::string> result; size_t start=0;
  for(size_t i=0;i<readings.size();++i){ if(readings[i]=='-'){ if(i>start) result.push_back(readings.substr(start,i-start)); start=i+1;}}
  if(start<readings.size()) result.push_back(readings.substr(start)); return result;
}
ReadingGrid makeGrid(ParselessLM* lm){
  ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(lm,[](Formosa::Gramambular2::LanguageModel*){}));
  grid.setReadingSeparator("-"); return grid;
}
bool feed(ReadingGrid& grid,const std::string& readings){
  for(const auto& syl:splitSyllables(readings)){ grid.setCursor(grid.length()); if(!grid.insertReading(syl)) return false;} return true;
}
std::string joinedWalk(const ReadingGrid::WalkResult& w){ std::string s; for(size_t i=0;i<w.nodes.size();++i) s+=w.chosenValueAt(i); return s;}
std::string joinedWords(const std::vector<std::string>& words){ std::string s; for(const auto& w:words) s+=w; return s;}
struct Case{std::string readings,expected;};
std::vector<Case> loadCases(const std::string& path){
  std::ifstream in(path); std::vector<Case> cases; std::string line;
  while(std::getline(in,line)){ if(line.empty()||line[0]=='#') continue; size_t tab=line.find('\t'); if(tab==std::string::npos) continue;
    cases.push_back({line.substr(0,tab),line.substr(tab+1)});} return cases;}
std::string peekMagic(const std::string& path){ std::ifstream in(path,std::ios::binary); char m[8]={}; in.read(m,8); return std::string(m,m+8);}
}
int main(int argc,char**argv){
  if(argc<9){std::cerr<<"Usage: ... sentences data bigrams lambda weights nu nbest out\n";return 1;}
  auto cases=loadCases(argv[1]);
  ParselessLM lm; if(!lm.open(argv[2])) return 1;
  CorpusBigramContextModel cm; if(!cm.load(argv[3])) return 1; cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer lstm; NeuralTFPathScorer tf; ReadingGrid::PathScorer* scorer=nullptr;
  auto magic=peekMagic(argv[5]);
  if(magic==std::string("LWLSTM1\0",8)){ if(!lstm.load(argv[5])) return 1; scorer=&lstm; std::cout<<"scorer=LSTM params="<<lstm.parameterCount()<<"\n";}
  else if(magic==std::string("LWTFMR1\0",8)){ if(!tf.load(argv[5])) return 1; scorer=&tf; std::cout<<"scorer=TF params="<<tf.parameterCount()<<"\n";}
  else return 1;
  double nu=std::stod(argv[6]); size_t nbestN=std::stoul(argv[7]); std::string outPath=argv[8];
  std::ofstream out(outPath);
  out<<"id\treading\tgold\twalk_out\trerank_out\tin_pool\tcorrect\n";
  int walkCorrect=0,rerankCorrect=0,inPool=0,poolWrong=0,poolMiss=0;
  for(size_t i=0;i<cases.size();++i){
    const auto& c=cases[i]; ReadingGrid g=makeGrid(&lm); if(!feed(g,c.readings)) continue;
    g.setContextModel(&cm); g.setPathScorer(nullptr); g.setPathRerankNu(0);
    auto walk=g.walk(); std::string walkOut=joinedWalk(walk); if(walkOut==c.expected) ++walkCorrect;
    auto nb=g.walkNBest(nbestN); bool goldIn=false;
    for(const auto& rp:nb) if(joinedWords(rp.words)==c.expected){goldIn=true;break;}
    if(goldIn) ++inPool;
    g.setPathScorer(scorer); g.setPathRerankNu(nu); g.setPathRerankNBest(nbestN);
    auto rerank=g.walk(); std::string rerankOut=joinedWalk(rerank); bool ok=rerankOut==c.expected;
    if(ok) ++rerankCorrect; if(goldIn&&!ok) ++poolWrong; if(!goldIn&&!ok) ++poolMiss;
    out<<(i+1)<<"\t"<<c.readings<<"\t"<<c.expected<<"\t"<<walkOut<<"\t"<<rerankOut<<"\t"<<(goldIn?'Y':'N')<<"\t"<<(ok?'Y':'N')<<"\n";
  }
  std::cout<<"WALK_ON "<<walkCorrect<<"/"<<cases.size()<<"\nRERANK "<<rerankCorrect<<"/"<<cases.size()
           <<"\nIN_POOL "<<inPool<<"/"<<cases.size()<<"\nPOOL_WRONG_SCORER "<<poolWrong<<"\nPOOL_MISS "<<poolMiss<<"\nOUT "<<outPath<<"\n";
  return 0;
}
